package normalize

import "encoding/json"

// TokenUsage is normalized usage for limiter reconciliation.
type TokenUsage struct {
	PromptTokens     int64
	CompletionTokens int64
	CachedPrompt     int64
	ReasoningTokens  int64
	EstimateOnly     bool
}

func UsageFromOpenAIChat(body []byte) TokenUsage {
	var v struct {
		Usage struct {
			PromptTokens        int64 `json:"prompt_tokens"`
			CompletionTokens    int64 `json:"completion_tokens"`
			TotalTokens         int64 `json:"total_tokens"`
			PromptTokensDetails *struct {
				CachedTokens int64 `json:"cached_tokens"`
			} `json:"prompt_tokens_details"`
			CompletionTokensDetails *struct {
				ReasoningTokens int64 `json:"reasoning_tokens"`
			} `json:"completion_tokens_details"`
		} `json:"usage"`
	}
	if json.Unmarshal(body, &v) != nil {
		return TokenUsage{EstimateOnly: true}
	}
	if v.Usage.PromptTokens == 0 && v.Usage.CompletionTokens == 0 && v.Usage.TotalTokens == 0 {
		return TokenUsage{EstimateOnly: true}
	}
	u := TokenUsage{
		PromptTokens:     v.Usage.PromptTokens,
		CompletionTokens: v.Usage.CompletionTokens,
	}
	if v.Usage.PromptTokensDetails != nil {
		u.CachedPrompt = v.Usage.PromptTokensDetails.CachedTokens
	}
	if v.Usage.CompletionTokensDetails != nil {
		u.ReasoningTokens = v.Usage.CompletionTokensDetails.ReasoningTokens
	}
	return u
}

func UsageFromOpenAIChunk(chunk []byte) (TokenUsage, bool) {
	var v struct {
		Usage *struct {
			PromptTokens     int64 `json:"prompt_tokens"`
			CompletionTokens int64 `json:"completion_tokens"`
		} `json:"usage"`
	}
	if json.Unmarshal(chunk, &v) != nil || v.Usage == nil {
		return TokenUsage{}, false
	}
	if v.Usage.PromptTokens == 0 && v.Usage.CompletionTokens == 0 {
		return TokenUsage{}, false
	}
	return TokenUsage{
		PromptTokens:     v.Usage.PromptTokens,
		CompletionTokens: v.Usage.CompletionTokens,
	}, true
}
