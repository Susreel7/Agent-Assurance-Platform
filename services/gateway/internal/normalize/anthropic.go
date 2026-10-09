package normalize

import (
	"encoding/json"
	"fmt"
	"time"

	"agent-assurance/services/gateway/internal/openai"
)

func AnthropicChatRequest(body []byte, deploymentModel string) ([]byte, error) {
	var req openai.ChatCompletionRequest
	if err := json.Unmarshal(body, &req); err != nil {
		return nil, err
	}
	maxTok := req.MaxTokens
	if maxTok == 0 {
		maxTok = req.MaxCompletionTok
	}
	if maxTok == 0 {
		maxTok = 1024
	}
	var messages []json.RawMessage
	_ = json.Unmarshal(req.Messages, &messages)
	systemParts, filtered, err := extractSystem(messages)
	if err != nil {
		return nil, err
	}
	out := map[string]any{
		"model":      deploymentModel,
		"max_tokens": maxTok,
		"messages":   filtered,
	}
	if len(systemParts) > 0 {
		out["system"] = systemParts
	}
	if req.Stream {
		out["stream"] = true
	}
	if req.Temperature != nil {
		out["temperature"] = *req.Temperature
	}
	if req.TopP != nil {
		out["top_p"] = *req.TopP
	}
	if len(req.Stop) > 0 {
		out["stop_sequences"] = req.Stop
	}
	if len(req.Tools) > 0 {
		out["tools"] = req.Tools
	}
	if len(req.ToolChoice) > 0 {
		out["tool_choice"] = req.ToolChoice
	}
	if len(req.ResponseFormat) > 0 {
		var rf map[string]any
		if json.Unmarshal(req.ResponseFormat, &rf) == nil {
			if rf["type"] == "json_schema" {
				out["response_format"] = rf
			} else {
				return nil, UnsupportedParam("response_format")
			}
		}
	}
	return json.Marshal(out)
}

func extractSystem(messages []json.RawMessage) (system []any, rest []json.RawMessage, err error) {
	for _, m := range messages {
		var probe struct {
			Role    string `json:"role"`
			Content any    `json:"content"`
		}
		if json.Unmarshal(m, &probe) != nil {
			rest = append(rest, m)
			continue
		}
		if probe.Role == "system" {
			system = append(system, probe.Content)
			continue
		}
		rest = append(rest, m)
	}
	return system, rest, nil
}

func AnthropicToOpenAIChat(body []byte, modelAlias string) ([]byte, error) {
	var msg struct {
		ID      string `json:"id"`
		Type    string `json:"type"`
		Role    string `json:"role"`
		Content []struct {
			Type  string          `json:"type"`
			Text  string          `json:"text"`
			ID    string          `json:"id"`
			Name  string          `json:"name"`
			Input json.RawMessage `json:"input"`
		} `json:"content"`
		StopReason string `json:"stop_reason"`
		Usage      struct {
			InputTokens  int `json:"input_tokens"`
			OutputTokens int `json:"output_tokens"`
		} `json:"usage"`
	}
	if err := json.Unmarshal(body, &msg); err != nil {
		return nil, err
	}
	text := ""
	var toolCalls []map[string]any
	for _, block := range msg.Content {
		switch block.Type {
		case "text":
			text += block.Text
		case "tool_use":
			toolCalls = append(toolCalls, map[string]any{
				"id": block.ID, "type": "function",
				"function": map[string]any{"name": block.Name, "arguments": string(block.Input)},
			})
		}
	}
	finish := mapStopReason(msg.StopReason)
	assistant := map[string]any{"role": "assistant", "content": text}
	if len(toolCalls) > 0 {
		assistant["tool_calls"] = toolCalls
		assistant["content"] = nil
	}
	resp := openai.ChatCompletion{
		ID:      msg.ID,
		Object:  "chat.completion",
		Created: time.Now().Unix(),
		Model:   modelAlias,
		Usage: openai.Usage{
			PromptTokens:     msg.Usage.InputTokens,
			CompletionTokens: msg.Usage.OutputTokens,
			TotalTokens:      msg.Usage.InputTokens + msg.Usage.OutputTokens,
		},
	}
	resp.Choices = append(resp.Choices, openai.ChatChoice{
		Index: 0,
		Message: openai.AssistantMessage{
			Role: "assistant", Content: mustRaw(assistant["content"]), ToolCalls: mustRaw(assistant["tool_calls"]),
		},
		FinishReason: finish,
	})
	return json.Marshal(resp)
}

func AnthropicErrorToOpenAI(status int, body []byte) ([]byte, int) {
	var er struct {
		Error struct {
			Type    string `json:"type"`
			Message string `json:"message"`
		} `json:"error"`
	}
	_ = json.Unmarshal(body, &er)
	msg := er.Error.Message
	if msg == "" {
		msg = string(body)
	}
	typ := openai.TypeServer
	if status == 400 {
		typ = openai.TypeInvalidRequest
	}
	if status == 401 || status == 403 {
		typ = openai.TypeAuth
	}
	code := "upstream_error"
	b, _ := json.Marshal(openai.ErrorResponse{Error: openai.ErrorBody{Message: msg, Type: typ, Code: &code}})
	return b, status
}

func mapStopReason(r string) string {
	switch r {
	case "end_turn", "stop_sequence":
		return "stop"
	case "tool_use":
		return "tool_calls"
	case "max_tokens":
		return "length"
	default:
		return r
	}
}

func mustRaw(v any) json.RawMessage {
	if v == nil {
		return nil
	}
	b, _ := json.Marshal(v)
	return b
}

func AnthropicOpUnsupported(op string) error {
	return fmt.Errorf("anthropic does not support operation %q", op)
}
