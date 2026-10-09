package provider

import (
	"context"
	"io"
	"net/http"

	"agent-assurance/services/gateway/internal/snapshot"
)

type Operation string

const (
	OpChat       Operation = "chat"
	OpResponses  Operation = "responses"
	OpEmbeddings Operation = "embeddings"
)

type InvokeRequest struct {
	Operation    Operation
	Deployment   snapshot.Deployment
	APIKey       string
	Body         []byte
	Stream       bool
	ExtraHeaders map[string]string
}

type InvokeResult struct {
	StatusCode int
	Headers    http.Header
	Body       io.ReadCloser
	TTFB       bool // first byte already sent to client when streaming
}

type Adapter interface {
	Name() string
	Invoke(ctx context.Context, req InvokeRequest) (*InvokeResult, error)
	SupportedParams(op Operation) map[string]struct{}
}

func ForProvider(name string) Adapter {
	switch name {
	case "openai", "openai_compatible":
		return &OpenAIAdapter{Compatible: name == "openai_compatible"}
	case "azure_openai":
		return &AzureOpenAIAdapter{}
	case "anthropic":
		return &AnthropicAdapter{}
	case "bedrock":
		return &BedrockAdapter{}
	case "gemini":
		return &GeminiAdapter{Vertex: false}
	case "vertex":
		return &GeminiAdapter{Vertex: true}
	default:
		return nil
	}
}
