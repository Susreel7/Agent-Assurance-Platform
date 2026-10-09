package handler

import (
	"encoding/json"
)

func usageFromChatJSON(body []byte) (prompt, completion int64) {
	var v struct {
		Usage struct {
			PromptTokens     int64 `json:"prompt_tokens"`
			CompletionTokens int64 `json:"completion_tokens"`
		} `json:"usage"`
	}
	if json.Unmarshal(body, &v) != nil {
		return 0, 0
	}
	return v.Usage.PromptTokens, v.Usage.CompletionTokens
}

func estimateTokensInOut(body []byte) (in, out int64) {
	in = int64(len(body) / 4)
	if in < 1 {
		in = 1
	}
	out = in / 2
	if out < 1 {
		out = 1
	}
	return in, out
}
