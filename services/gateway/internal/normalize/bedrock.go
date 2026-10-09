package normalize

import (
	"encoding/json"
	"time"

	"agent-assurance/services/gateway/internal/openai"
)

func BedrockConverseRequest(body []byte, modelID string) ([]byte, error) {
	mapped, err := AnthropicChatRequest(body, modelID)
	if err != nil {
		return nil, err
	}
	var anthropic map[string]any
	if err := json.Unmarshal(mapped, &anthropic); err != nil {
		return nil, err
	}
	msgs, _ := anthropic["messages"].([]any)
	conv := map[string]any{
		"modelId":  modelID,
		"messages": msgs,
	}
	if mt, ok := anthropic["max_tokens"]; ok {
		conv["inferenceConfig"] = map[string]any{"maxTokens": mt}
	}
	if sys, ok := anthropic["system"]; ok {
		conv["system"] = sys
	}
	return json.Marshal(conv)
}

func BedrockConverseToOpenAI(body []byte, modelAlias string) ([]byte, error) {
	var resp struct {
		Output struct {
			Message struct {
				Role    string `json:"role"`
				Content []struct {
					Text    string `json:"text"`
					ToolUse *struct {
						ToolUseID string          `json:"toolUseId"`
						Name      string          `json:"name"`
						Input     json.RawMessage `json:"input"`
					} `json:"toolUse"`
				} `json:"content"`
			} `json:"message"`
		} `json:"output"`
		StopReason string `json:"stopReason"`
		Usage      struct {
			InputTokens  int `json:"inputTokens"`
			OutputTokens int `json:"outputTokens"`
		} `json:"usage"`
	}
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, err
	}
	text := ""
	var toolCalls []map[string]any
	for _, c := range resp.Output.Message.Content {
		if c.Text != "" {
			text += c.Text
		}
		if c.ToolUse != nil {
			toolCalls = append(toolCalls, map[string]any{
				"id": c.ToolUse.ToolUseID, "type": "function",
				"function": map[string]any{"name": c.ToolUse.Name, "arguments": string(c.ToolUse.Input)},
			})
		}
	}
	assistant := map[string]any{"role": "assistant", "content": text}
	if len(toolCalls) > 0 {
		assistant["content"] = nil
		assistant["tool_calls"] = toolCalls
	}
	out := openai.ChatCompletion{
		ID: "bedrock-" + modelAlias, Object: "chat.completion", Created: time.Now().Unix(), Model: modelAlias,
		Usage: openai.Usage{
			PromptTokens: resp.Usage.InputTokens, CompletionTokens: resp.Usage.OutputTokens,
			TotalTokens: resp.Usage.InputTokens + resp.Usage.OutputTokens,
		},
	}
	out.Choices = append(out.Choices, openai.ChatChoice{
		Index:        0,
		Message:      openai.AssistantMessage{Role: "assistant", Content: mustRaw(assistant["content"]), ToolCalls: mustRaw(assistant["tool_calls"])},
		FinishReason: mapStopReason(resp.StopReason),
	})
	return json.Marshal(out)
}
