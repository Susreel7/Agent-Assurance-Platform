package provider

import (
	"encoding/json"
	"fmt"
)

// ValidateUnsupported scans top-level JSON keys and rejects unknown knobs per adapter.
func ValidateUnsupported(body []byte, allowed map[string]struct{}) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(body, &raw); err != nil {
		return fmt.Errorf("invalid json body")
	}
	for k := range raw {
		if _, ok := allowed[k]; !ok {
			return fmt.Errorf("unsupported parameter %q for this provider", k)
		}
	}
	return nil
}

func BaseChatParams() map[string]struct{} {
	return map[string]struct{}{
		"model": {}, "messages": {}, "stream": {}, "temperature": {}, "top_p": {},
		"max_tokens": {}, "max_completion_tokens": {}, "stop": {}, "tools": {}, "tool_choice": {},
		"response_format": {}, "user": {}, "n": {}, "presence_penalty": {}, "frequency_penalty": {},
		"seed": {}, "logprobs": {}, "top_logprobs": {}, "stream_options": {},
	}
}

func BaseEmbeddingParams() map[string]struct{} {
	return map[string]struct{}{
		"model": {}, "input": {}, "encoding_format": {}, "dimensions": {}, "user": {},
	}
}

func BaseResponsesParams() map[string]struct{} {
	return map[string]struct{}{
		"model": {}, "input": {}, "stream": {}, "tools": {}, "tool_choice": {},
		"text": {}, "temperature": {}, "top_p": {}, "max_output_tokens": {}, "metadata": {},
		"reasoning": {},
	}
}

func RequireCapability(caps []string, need string) error {
	for _, c := range caps {
		if c == need {
			return nil
		}
	}
	return fmt.Errorf("deployment missing capability %q", need)
}

func HasTools(body []byte) bool {
	var probe struct {
		Tools json.RawMessage `json:"tools"`
	}
	_ = json.Unmarshal(body, &probe)
	return len(probe.Tools) > 0
}

func HasJSONSchema(body []byte) bool {
	var probe struct {
		ResponseFormat json.RawMessage `json:"response_format"`
	}
	_ = json.Unmarshal(body, &probe)
	return len(probe.ResponseFormat) > 0
}

func HasVision(body []byte) bool {
	var probe struct {
		Messages []struct {
			Content json.RawMessage `json:"content"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(body, &probe); err != nil {
		return false
	}
	for _, m := range probe.Messages {
		if len(m.Content) > 0 && m.Content[0] == '[' {
			return true
		}
	}
	return false
}
