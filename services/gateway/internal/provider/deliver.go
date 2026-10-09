package provider

import (
	"context"
	"io"
	"net/http"

	"agent-assurance/services/gateway/internal/normalize"
	"agent-assurance/services/gateway/internal/openai"
	"agent-assurance/services/gateway/internal/snapshot"
	"agent-assurance/services/gateway/internal/sse"
)

func DeliverChat(ctx context.Context, w http.ResponseWriter, dep snapshot.Deployment, res *InvokeResult, stream bool, modelAlias string, maxBody int64) (DeliveryResult, error) {
	defer res.Body.Close()
	name := dep.Provider
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(res.Body, 1<<20))
		err := writeNormalizedError(w, name, res.StatusCode, body)
		return DeliveryResult{Status: res.StatusCode}, err
	}
	if stream {
		usage, err := deliverChatStream(ctx, w, name, res.Body, modelAlias)
		return DeliveryResult{Usage: usage, Cacheable: false}, err
	}
	body, err := io.ReadAll(io.LimitReader(res.Body, maxBody))
	if err != nil {
		return DeliveryResult{}, err
	}
	out, err := normalizeChatSuccess(name, body, modelAlias)
	if err != nil {
		openai.WriteError(w, http.StatusBadGateway, openai.TypeServer, err.Error(), "normalize_error")
		return DeliveryResult{}, err
	}
	usage := normalize.UsageFromOpenAIChat(out)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, err = w.Write(out)
	return DeliveryResult{Usage: usage, ResponseBody: out, Status: http.StatusOK, Cacheable: true}, err
}

func deliverChatStream(ctx context.Context, w http.ResponseWriter, provider string, body io.Reader, modelAlias string) (normalize.TokenUsage, error) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	switch provider {
	case "openai", "openai_compatible", "azure_openai":
		return sse.RelayResponsesRaw(ctx, w, body)
	case "anthropic":
		return normalize.StreamAnthropicToOpenAI(ctx, body, w, modelAlias)
	case "gemini", "vertex":
		return normalize.StreamGeminiSSEToOpenAI(ctx, body, w, modelAlias)
	case "bedrock":
		return normalize.StreamBedrockConverseToOpenAI(ctx, body, w, modelAlias)
	default:
		return sse.RelayWithUsage(ctx, w, body)
	}
}

func DeliverResponses(ctx context.Context, w http.ResponseWriter, dep snapshot.Deployment, res *InvokeResult, stream bool, modelAlias string, maxBody int64) (DeliveryResult, error) {
	defer res.Body.Close()
	name := dep.Provider
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(res.Body, 1<<20))
		err := writeNormalizedError(w, name, res.StatusCode, body)
		return DeliveryResult{Status: res.StatusCode}, err
	}
	if stream {
		switch name {
		case "openai", "openai_compatible", "azure_openai":
			w.Header().Set("Content-Type", "text/event-stream")
			w.Header().Set("Cache-Control", "no-cache")
			w.WriteHeader(http.StatusOK)
			usage, err := sse.RelayResponses(ctx, w, res.Body)
			return DeliveryResult{Usage: usage}, err
		default:
			if !hasCapability(dep.Capabilities, "responses_stream") {
				openai.WriteError(w, http.StatusNotImplemented, openai.TypeInvalidRequest,
					"responses streaming requires responses_stream capability for this provider", "responses_stream_unsupported")
				return DeliveryResult{}, ErrNonRetryable
			}
			usage, err := normalize.StreamChatToResponsesSSE(ctx, name, res.Body, w, modelAlias)
			return DeliveryResult{Usage: usage}, err
		}
	}
	bodyOut, err := io.ReadAll(io.LimitReader(res.Body, maxBody))
	if err != nil {
		return DeliveryResult{}, err
	}
	out, status, err := normalizeResponsesBody(name, res.StatusCode, bodyOut)
	if err != nil {
		openai.WriteError(w, http.StatusBadGateway, openai.TypeServer, err.Error(), "normalize_error")
		return DeliveryResult{}, err
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(out)
	usage := normalize.UsageFromOpenAIChat(out)
	return DeliveryResult{Usage: usage, ResponseBody: out, Status: status, Cacheable: status >= 200 && status < 300}, nil
}

func normalizeResponsesBody(depName string, status int, body []byte) ([]byte, int, error) {
	if status < 200 || status >= 300 {
		return body, status, nil
	}
	switch depName {
	case "openai", "openai_compatible", "azure_openai":
		return body, status, nil
	default:
		out, err := normalize.ResponsesPassthroughOrChat(body, depName)
		if err != nil {
			return nil, http.StatusBadRequest, err
		}
		return out, http.StatusOK, nil
	}
}

func DeliverResponsesJSON(w http.ResponseWriter, depName string, status int, body []byte) {
	if status < 200 || status >= 300 {
		_ = writeNormalizedError(w, depName, status, body)
		return
	}
	switch depName {
	case "openai", "openai_compatible", "azure_openai":
		writeJSON(w, status, body)
	default:
		out, err := normalize.ResponsesPassthroughOrChat(body, depName)
		if err != nil {
			openaiWrite(w, http.StatusBadRequest, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, out)
	}
}

func hasCapability(caps []string, need string) bool {
	for _, c := range caps {
		if c == need {
			return true
		}
	}
	return false
}

func normalizeChatSuccess(provider string, body []byte, modelAlias string) ([]byte, error) {
	switch provider {
	case "openai", "openai_compatible", "azure_openai":
		return body, nil
	case "anthropic":
		return normalize.AnthropicToOpenAIChat(body, modelAlias)
	case "gemini", "vertex":
		return normalize.GeminiToOpenAIChat(body, modelAlias)
	case "bedrock":
		return normalize.BedrockConverseToOpenAI(body, modelAlias)
	default:
		return body, nil
	}
}

func writeNormalizedError(w http.ResponseWriter, provider string, status int, body []byte) error {
	var out []byte
	var st = status
	switch provider {
	case "anthropic":
		out, st = normalize.AnthropicErrorToOpenAI(status, body)
	default:
		code := "upstream_error"
		out, st = normalize.FormatUpstreamError(status, openai.TypeServer, string(body), code)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(st)
	_, err := w.Write(out)
	return err
}
