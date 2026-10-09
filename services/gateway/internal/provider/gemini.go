package provider

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"

	"agent-assurance/services/gateway/internal/normalize"
)

type GeminiAdapter struct {
	Vertex bool
}

func (a *GeminiAdapter) Name() string {
	if a.Vertex {
		return "vertex"
	}
	return "gemini"
}

func (a *GeminiAdapter) SupportedParams(op Operation) map[string]struct{} {
	switch op {
	case OpEmbeddings:
		return map[string]struct{}{"model": {}, "input": {}}
	case OpResponses:
		return map[string]struct{}{"model": {}, "input": {}, "stream": {}}
	default:
		return map[string]struct{}{
			"model": {}, "messages": {}, "stream": {}, "temperature": {}, "top_p": {},
			"max_tokens": {}, "max_completion_tokens": {}, "tools": {}, "tool_choice": {}, "response_format": {},
		}
	}
}

func (a *GeminiAdapter) Invoke(ctx context.Context, req InvokeRequest) (*InvokeResult, error) {
	switch req.Operation {
	case OpChat, OpResponses:
		mapped, err := normalize.GeminiChatRequest(req.Body, req.Deployment.Model)
		if err != nil {
			return nil, err
		}
		target, err := a.generateURL(req, req.Stream)
		if err != nil {
			return nil, err
		}
		headers := map[string]string{}
		if a.Vertex {
			headers["Authorization"] = "Bearer " + req.APIKey
		} else {
			target = target + "?key=" + url.QueryEscape(req.APIKey)
		}
		for k, v := range req.ExtraHeaders {
			headers[k] = v
		}
		resp, err := doUpstream(ctx, http.MethodPost, target, headers, mapped)
		if err != nil {
			return nil, err
		}
		return &InvokeResult{StatusCode: resp.StatusCode, Headers: cloneHeaders(resp.Header), Body: resp.Body}, nil
	case OpEmbeddings:
		mapped, err := normalize.GeminiEmbeddingsRequest(req.Body)
		if err != nil {
			return nil, err
		}
		target := joinURL(req.Deployment.Endpoint, "/v1beta/models/"+url.PathEscape(req.Deployment.Model)+":embedContent")
		if a.Vertex {
			target = joinURL(req.Deployment.Endpoint, fmt.Sprintf("/v1/projects/-/locations/%s/publishers/google/models/%s:embedContent",
				url.PathEscape(req.Deployment.Region), url.PathEscape(req.Deployment.Model)))
		} else {
			target = target + "?key=" + url.QueryEscape(req.APIKey)
		}
		headers := map[string]string{}
		if a.Vertex {
			headers["Authorization"] = "Bearer " + req.APIKey
		}
		resp, err := doUpstream(ctx, http.MethodPost, target, headers, mapped)
		if err != nil {
			return nil, err
		}
		return &InvokeResult{StatusCode: resp.StatusCode, Headers: cloneHeaders(resp.Header), Body: resp.Body}, nil
	default:
		return nil, fmt.Errorf("unsupported operation")
	}
}

func (a *GeminiAdapter) generateURL(req InvokeRequest, stream bool) (string, error) {
	model := req.Deployment.Model
	if a.Vertex {
		base := strings.TrimRight(req.Deployment.Endpoint, "/")
		op := "generateContent"
		if stream {
			op = "streamGenerateContent"
		}
		u := fmt.Sprintf("%s/v1/projects/-/locations/%s/publishers/google/models/%s:%s",
			base, url.PathEscape(req.Deployment.Region), url.PathEscape(model), op)
		if stream {
			u += "?alt=sse"
		}
		return u, nil
	}
	op := "generateContent"
	if stream {
		op = "streamGenerateContent"
	}
	u := joinURL(req.Deployment.Endpoint, "/v1beta/models/"+url.PathEscape(model)+":"+op)
	if stream {
		u += "?alt=sse"
	}
	return u, nil
}
