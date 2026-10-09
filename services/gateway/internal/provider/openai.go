package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"agent-assurance/services/gateway/internal/normalize"
)

type OpenAIAdapter struct {
	Compatible bool
}

func (a *OpenAIAdapter) Name() string {
	if a.Compatible {
		return "openai_compatible"
	}
	return "openai"
}

func (a *OpenAIAdapter) SupportedParams(op Operation) map[string]struct{} {
	switch op {
	case OpEmbeddings:
		return BaseEmbeddingParams()
	case OpResponses:
		return BaseResponsesParams()
	default:
		return BaseChatParams()
	}
}

func (a *OpenAIAdapter) Invoke(ctx context.Context, req InvokeRequest) (*InvokeResult, error) {
	path := "/v1/chat/completions"
	switch req.Operation {
	case OpEmbeddings:
		path = "/v1/embeddings"
	case OpResponses:
		path = "/v1/responses"
	}
	url := joinURL(req.Deployment.Endpoint, path)
	headers := map[string]string{"Authorization": "Bearer " + req.APIKey}
	for k, v := range req.ExtraHeaders {
		headers[k] = v
	}
	resp, err := doUpstream(ctx, http.MethodPost, url, headers, req.Body)
	if err != nil {
		return nil, err
	}
	return &InvokeResult{StatusCode: resp.StatusCode, Headers: cloneHeaders(resp.Header), Body: resp.Body}, nil
}

type AzureOpenAIAdapter struct{}

func (a *AzureOpenAIAdapter) Name() string { return "azure_openai" }

func (a *AzureOpenAIAdapter) SupportedParams(op Operation) map[string]struct{} {
	switch op {
	case OpEmbeddings:
		return BaseEmbeddingParams()
	case OpResponses:
		return BaseResponsesParams()
	default:
		return BaseChatParams()
	}
}

func (a *AzureOpenAIAdapter) Invoke(ctx context.Context, req InvokeRequest) (*InvokeResult, error) {
	apiVersion := AzureAPIVersionFromEndpoint(req.Deployment.Endpoint)
	var url string
	var err error
	switch req.Operation {
	case OpChat:
		url, err = AzureChatURL(req.Deployment.Endpoint, req.Deployment.Model, apiVersion)
	case OpEmbeddings:
		url, err = AzureEmbeddingsURL(req.Deployment.Endpoint, req.Deployment.Model, apiVersion)
	case OpResponses:
		url, err = AzureResponsesURL(req.Deployment.Endpoint, req.Deployment.Model, apiVersion)
	default:
		return nil, fmt.Errorf("unsupported operation")
	}
	if err != nil {
		return nil, err
	}
	headers := map[string]string{"api-key": req.APIKey}
	for k, v := range req.ExtraHeaders {
		headers[k] = v
	}
	resp, err := doUpstream(ctx, http.MethodPost, url, headers, req.Body)
	if err != nil {
		return nil, err
	}
	return &InvokeResult{StatusCode: resp.StatusCode, Headers: cloneHeaders(resp.Header), Body: resp.Body}, nil
}

func DeliverEmbeddings(w http.ResponseWriter, depName string, status int, body []byte, modelAlias string, max int64) {
	_ = max
	if status < 200 || status >= 300 {
		_ = writeNormalizedError(w, depName, status, body)
		return
	}
	switch depName {
	case "gemini", "vertex":
		out, err := normalize.GeminiEmbeddingsToOpenAI(body, modelAlias)
		if err != nil {
			openaiWrite(w, http.StatusBadGateway, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, out)
	default:
		writeJSON(w, status, body)
	}
}

func writeJSON(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

func openaiWrite(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, mustJSON(map[string]any{"error": map[string]any{"message": msg, "type": "server_error"}}))
}

func mustJSON(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}
