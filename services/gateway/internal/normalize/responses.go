package normalize

import (
	"encoding/json"
	"fmt"
)

func ResponsesPassthroughOrChat(body []byte, provider string) ([]byte, error) {
	var chat []byte
	var err error
	switch provider {
	case "anthropic":
		chat, err = AnthropicToOpenAIChat(body, "responses-mapped")
	case "bedrock":
		chat, err = BedrockConverseToOpenAI(body, "responses-mapped")
	case "gemini", "vertex":
		chat, err = GeminiToOpenAIChat(body, "responses-mapped")
	default:
		return nil, fmt.Errorf("responses not supported for %s", provider)
	}
	if err != nil {
		return nil, err
	}
	var c map[string]any
	if err := json.Unmarshal(chat, &c); err != nil {
		return nil, err
	}
	text := ""
	if choices, ok := c["choices"].([]any); ok && len(choices) > 0 {
		if ch, ok := choices[0].(map[string]any); ok {
			if msg, ok := ch["message"].(map[string]any); ok {
				if content, ok := msg["content"].(string); ok {
					text = content
				}
			}
		}
	}
	return json.Marshal(map[string]any{
		"id": "resp_mapped", "object": "response", "status": "completed",
		"output": []map[string]any{{"type": "message", "role": "assistant", "content": text}},
	})
}
