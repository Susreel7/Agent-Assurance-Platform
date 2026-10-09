package provider

import (
	"context"
	"fmt"
	"net/http"

	"agent-assurance/services/gateway/internal/normalize"
)

type AnthropicAdapter struct{}

func (a *AnthropicAdapter) Name() string { return "anthropic" }

func (a *AnthropicAdapter) SupportedParams(op Operation) map[string]struct{} {
	switch op {
	case OpEmbeddings, OpResponses:
		return map[string]struct{}{"model": {}}
	default:
		return map[string]struct{}{
			"model": {}, "messages": {}, "max_tokens": {}, "max_completion_tokens": {},
			"stream": {}, "temperature": {}, "top_p": {}, "stop": {}, "tools": {}, "tool_choice": {},
			"response_format": {},
		}
	}
}

func (a *AnthropicAdapter) Invoke(ctx context.Context, req InvokeRequest) (*InvokeResult, error) {
	switch req.Operation {
	case OpChat:
		mapped, err := normalize.AnthropicChatRequest(req.Body, req.Deployment.Model)
		if err != nil {
			return nil, err
		}
		url := joinURL(req.Deployment.Endpoint, "/v1/messages")
		headers := map[string]string{"x-api-key": req.APIKey, "anthropic-version": "2023-06-01"}
		for k, v := range req.ExtraHeaders {
			headers[k] = v
		}
		resp, err := doUpstream(ctx, http.MethodPost, url, headers, mapped)
		if err != nil {
			return nil, err
		}
		return &InvokeResult{StatusCode: resp.StatusCode, Headers: cloneHeaders(resp.Header), Body: resp.Body}, nil
	case OpResponses, OpEmbeddings:
		return nil, normalize.AnthropicOpUnsupported(string(req.Operation))
	default:
		return nil, fmt.Errorf("unsupported operation")
	}
}
