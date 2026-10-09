package normalize

import (
	"encoding/json"
	"fmt"
	"time"

	"agent-assurance/services/gateway/internal/openai"
)

func GeminiChatRequest(body []byte, deploymentModel string) ([]byte, error) {
	var req openai.ChatCompletionRequest
	if err := json.Unmarshal(body, &req); err != nil {
		return nil, err
	}
	var messages []struct {
		Role    string          `json:"role"`
		Content json.RawMessage `json:"content"`
	}
	if err := json.Unmarshal(req.Messages, &messages); err != nil {
		return nil, err
	}
	contents := make([]map[string]any, 0, len(messages))
	for _, m := range messages {
		role := m.Role
		if role == "assistant" {
			role = "model"
		}
		if role == "system" {
			role = "user"
		}
		parts, err := contentToParts(m.Content)
		if err != nil {
			return nil, err
		}
		contents = append(contents, map[string]any{"role": role, "parts": parts})
	}
	out := map[string]any{"contents": contents}
	genConfig := map[string]any{}
	if req.Temperature != nil {
		genConfig["temperature"] = *req.Temperature
	}
	if req.TopP != nil {
		genConfig["topP"] = *req.TopP
	}
	maxTok := req.MaxTokens
	if maxTok == 0 {
		maxTok = req.MaxCompletionTok
	}
	if maxTok > 0 {
		genConfig["maxOutputTokens"] = maxTok
	}
	if len(genConfig) > 0 {
		out["generationConfig"] = genConfig
	}
	if len(req.Tools) > 0 {
		out["tools"] = req.Tools
	}
	if len(req.ResponseFormat) > 0 {
		var rf map[string]any
		if json.Unmarshal(req.ResponseFormat, &rf) == nil && rf["type"] == "json_object" {
			out["generationConfig"] = map[string]any{"responseMimeType": "application/json"}
		} else {
			return nil, UnsupportedParam("response_format")
		}
	}
	_ = deploymentModel
	return json.Marshal(out)
}

func contentToParts(content json.RawMessage) ([]map[string]any, error) {
	if len(content) == 0 {
		return []map[string]any{{"text": ""}}, nil
	}
	if content[0] == '"' {
		var s string
		if err := json.Unmarshal(content, &s); err != nil {
			return nil, err
		}
		return []map[string]any{{"text": s}}, nil
	}
	if content[0] == '[' {
		var blocks []struct {
			Type     string `json:"type"`
			Text     string `json:"text"`
			ImageURL *struct {
				URL string `json:"url"`
			} `json:"image_url"`
		}
		if err := json.Unmarshal(content, &blocks); err != nil {
			return nil, err
		}
		parts := make([]map[string]any, 0, len(blocks))
		for _, b := range blocks {
			switch b.Type {
			case "text":
				parts = append(parts, map[string]any{"text": b.Text})
			case "image_url":
				if b.ImageURL != nil {
					parts = append(parts, map[string]any{"inlineData": map[string]any{
						"mimeType": "image/jpeg", "data": b.ImageURL.URL,
					}})
				}
			default:
				return nil, UnsupportedParam("content block " + b.Type)
			}
		}
		return parts, nil
	}
	return nil, fmt.Errorf("unsupported message content")
}

func GeminiToOpenAIChat(body []byte, modelAlias string) ([]byte, error) {
	var resp struct {
		Candidates []struct {
			Content struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"content"`
			FinishReason string `json:"finishReason"`
		} `json:"candidates"`
		UsageMetadata struct {
			PromptTokenCount        int `json:"promptTokenCount"`
			CandidatesTokenCount    int `json:"candidatesTokenCount"`
			CachedContentTokenCount int `json:"cachedContentTokenCount"`
		} `json:"usageMetadata"`
	}
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, err
	}
	text := ""
	finish := "stop"
	if len(resp.Candidates) > 0 {
		for _, p := range resp.Candidates[0].Content.Parts {
			text += p.Text
		}
		finish = mapGeminiFinish(resp.Candidates[0].FinishReason)
	}
	out := openai.ChatCompletion{
		ID: "gemini-" + fmt.Sprint(time.Now().UnixNano()), Object: "chat.completion",
		Created: time.Now().Unix(), Model: modelAlias,
		Usage: openai.Usage{
			PromptTokens:       resp.UsageMetadata.PromptTokenCount,
			CompletionTokens:   resp.UsageMetadata.CandidatesTokenCount,
			TotalTokens:        resp.UsageMetadata.PromptTokenCount + resp.UsageMetadata.CandidatesTokenCount,
			CachedPromptTokens: resp.UsageMetadata.CachedContentTokenCount,
		},
	}
	out.Choices = append(out.Choices, openai.ChatChoice{
		Index:        0,
		Message:      openai.AssistantMessage{Role: "assistant", Content: mustRaw(text)},
		FinishReason: finish,
	})
	return json.Marshal(out)
}

func mapGeminiFinish(r string) string {
	switch r {
	case "STOP":
		return "stop"
	case "MAX_TOKENS":
		return "length"
	default:
		return "stop"
	}
}

func GeminiEmbeddingsRequest(body []byte) ([]byte, error) {
	var req struct {
		Input json.RawMessage `json:"input"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		return nil, err
	}
	return json.Marshal(map[string]any{"content": map[string]any{"parts": []map[string]any{{"text": req.Input}}}})
}

func GeminiEmbeddingsToOpenAI(body []byte, modelAlias string) ([]byte, error) {
	var resp struct {
		Embedding struct {
			Values []float64 `json:"values"`
		} `json:"embedding"`
	}
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, err
	}
	return json.Marshal(map[string]any{
		"object": "list",
		"data": []map[string]any{{
			"object": "embedding", "index": 0, "embedding": resp.Embedding.Values,
		}},
		"model": modelAlias,
		"usage": map[string]int{"prompt_tokens": 0, "total_tokens": 0},
	})
}
