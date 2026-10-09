package normalize

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"agent-assurance/services/gateway/internal/bedrockstream"
	"agent-assurance/services/gateway/internal/openai"
)

func WriteOpenAIChunk(w http.ResponseWriter, flusher http.Flusher, chunk openai.ChatCompletionChunk) error {
	b, _ := json.Marshal(chunk)
	if _, err := fmt.Fprintf(w, "data: %s\n\n", b); err != nil {
		return err
	}
	flusher.Flush()
	return nil
}

func StreamAnthropicToOpenAI(ctx context.Context, r io.Reader, w http.ResponseWriter, modelAlias string) (TokenUsage, error) {
	fl, ok := w.(http.Flusher)
	if !ok {
		return TokenUsage{EstimateOnly: true}, fmt.Errorf("response writer does not flush")
	}
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	id := "chatcmpl-stream"
	created := time.Now().Unix()
	var finishReason string
	var promptTokens, completionTokens int64
	var emitted bool
	for sc.Scan() {
		if err := ctx.Err(); err != nil {
			return streamAbort(emitted, promptTokens, completionTokens, err)
		}
		line := sc.Bytes()
		if !bytes.HasPrefix(line, []byte("data:")) {
			continue
		}
		payload := bytes.TrimSpace(line[5:])
		if len(payload) == 0 || bytes.Equal(payload, []byte("[DONE]")) {
			continue
		}
		var ev struct {
			Type  string `json:"type"`
			Delta struct {
				Type        string `json:"type"`
				Text        string `json:"text"`
				PartialJSON string `json:"partial_json"`
				Thinking    string `json:"thinking"`
			} `json:"delta"`
			ContentBlock struct {
				Type string `json:"type"`
				Text string `json:"text"`
			} `json:"content_block"`
			Message struct {
				Usage struct {
					InputTokens  int64 `json:"input_tokens"`
					OutputTokens int64 `json:"output_tokens"`
				} `json:"usage"`
			} `json:"message"`
		}
		if json.Unmarshal(payload, &ev) != nil {
			continue
		}
		switch ev.Type {
		case "message_delta":
			if ev.Message.Usage.OutputTokens > 0 {
				completionTokens = ev.Message.Usage.OutputTokens
			}
			if ev.Message.Usage.InputTokens > 0 {
				promptTokens = ev.Message.Usage.InputTokens
			}
		case "message_stop":
			finishReason = "stop"
		}
		deltaObj := map[string]any{}
		switch ev.Type {
		case "content_block_delta":
			switch ev.Delta.Type {
			case "text_delta":
				if ev.Delta.Text != "" {
					deltaObj["content"] = ev.Delta.Text
				}
			case "input_json_delta":
				if ev.Delta.PartialJSON != "" {
					deltaObj["tool_calls"] = []map[string]any{{"index": 0, "function": map[string]any{"arguments": ev.Delta.PartialJSON}}}
				}
			case "thinking_delta":
				if ev.Delta.Thinking != "" {
					deltaObj["reasoning_content"] = ev.Delta.Thinking
				}
			}
		}
		if len(deltaObj) == 0 {
			continue
		}
		delta, _ := json.Marshal(deltaObj)
		chunk := openai.ChatCompletionChunk{
			ID: id, Object: "chat.completion.chunk", Created: created, Model: modelAlias,
		}
		chunk.Choices = append(chunk.Choices, openai.ChatChunkChoice{Index: 0, Delta: delta})
		if err := WriteOpenAIChunk(w, fl, chunk); err != nil {
			return streamAbort(true, promptTokens, completionTokens, err)
		}
		emitted = true
	}
	if err := sc.Err(); err != nil {
		return streamAbort(emitted, promptTokens, completionTokens, err)
	}
	if finishReason != "" {
		fr := finishReason
		delta, _ := json.Marshal(map[string]any{})
		chunk := openai.ChatCompletionChunk{ID: id, Object: "chat.completion.chunk", Created: created, Model: modelAlias}
		chunk.Choices = append(chunk.Choices, openai.ChatChunkChoice{Index: 0, Delta: delta, FinishReason: &fr})
		_ = WriteOpenAIChunk(w, fl, chunk)
	}
	if promptTokens > 0 || completionTokens > 0 {
		chunk := openai.ChatCompletionChunk{ID: id, Object: "chat.completion.chunk", Created: created, Model: modelAlias}
		chunk.Usage = &openai.Usage{PromptTokens: int(promptTokens), CompletionTokens: int(completionTokens), TotalTokens: int(promptTokens + completionTokens)}
		_ = WriteOpenAIChunk(w, fl, chunk)
	}
	return streamComplete(w, fl, promptTokens, completionTokens)
}

func StreamGeminiSSEToOpenAI(ctx context.Context, r io.Reader, w http.ResponseWriter, modelAlias string) (TokenUsage, error) {
	fl, ok := w.(http.Flusher)
	if !ok {
		return TokenUsage{EstimateOnly: true}, fmt.Errorf("response writer does not flush")
	}
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	id := "chatcmpl-gemini"
	var promptTokens, completionTokens int64
	var emitted bool
	created := time.Now().Unix()
	for sc.Scan() {
		if err := ctx.Err(); err != nil {
			return streamAbort(emitted, promptTokens, completionTokens, err)
		}
		line := sc.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		var resp struct {
			Candidates []struct {
				Content struct {
					Parts []struct {
						Text         string `json:"text"`
						FunctionCall *struct {
							Name string `json:"name"`
							Args string `json:"args"`
						} `json:"functionCall"`
						ExecutableCode string `json:"executableCode"`
					} `json:"parts"`
				} `json:"content"`
				FinishReason string `json:"finishReason"`
			} `json:"candidates"`
			UsageMetadata struct {
				PromptTokenCount     int64 `json:"promptTokenCount"`
				CandidatesTokenCount int64 `json:"candidatesTokenCount"`
			} `json:"usageMetadata"`
		}
		if json.Unmarshal([]byte(payload), &resp) != nil {
			continue
		}
		if len(resp.Candidates) == 0 {
			continue
		}
		cand := resp.Candidates[0]
		deltaObj := map[string]any{}
		for _, p := range cand.Content.Parts {
			if p.Text != "" {
				deltaObj["content"] = p.Text
			}
			if p.FunctionCall != nil {
				deltaObj["tool_calls"] = []map[string]any{{"function": map[string]any{"name": p.FunctionCall.Name, "arguments": p.FunctionCall.Args}}}
			}
			if p.ExecutableCode != "" {
				deltaObj["reasoning_content"] = p.ExecutableCode
			}
		}
		if len(deltaObj) > 0 {
			delta, _ := json.Marshal(deltaObj)
			chunk := openai.ChatCompletionChunk{ID: id, Object: "chat.completion.chunk", Created: created, Model: modelAlias}
			chunk.Choices = append(chunk.Choices, openai.ChatChunkChoice{Index: 0, Delta: delta})
			if err := WriteOpenAIChunk(w, fl, chunk); err != nil {
				return streamAbort(true, promptTokens, completionTokens, err)
			}
			emitted = true
		}
		if resp.UsageMetadata.PromptTokenCount > 0 {
			promptTokens = resp.UsageMetadata.PromptTokenCount
		}
		if resp.UsageMetadata.CandidatesTokenCount > 0 {
			completionTokens = resp.UsageMetadata.CandidatesTokenCount
		}
		if cand.FinishReason != "" {
			fr := strings.ToLower(cand.FinishReason)
			delta, _ := json.Marshal(map[string]any{})
			chunk := openai.ChatCompletionChunk{ID: id, Object: "chat.completion.chunk", Created: created, Model: modelAlias}
			chunk.Choices = append(chunk.Choices, openai.ChatChunkChoice{Index: 0, Delta: delta, FinishReason: &fr})
			_ = WriteOpenAIChunk(w, fl, chunk)
		}
		if resp.UsageMetadata.PromptTokenCount > 0 || resp.UsageMetadata.CandidatesTokenCount > 0 {
			chunk := openai.ChatCompletionChunk{ID: id, Object: "chat.completion.chunk", Created: created, Model: modelAlias}
			pt, ct := resp.UsageMetadata.PromptTokenCount, resp.UsageMetadata.CandidatesTokenCount
			chunk.Usage = &openai.Usage{PromptTokens: int(pt), CompletionTokens: int(ct), TotalTokens: int(pt + ct)}
			_ = WriteOpenAIChunk(w, fl, chunk)
		}
	}
	if err := sc.Err(); err != nil {
		return streamAbort(emitted, promptTokens, completionTokens, err)
	}
	return streamComplete(w, fl, promptTokens, completionTokens)
}

func StreamBedrockConverseToOpenAI(ctx context.Context, r io.Reader, w http.ResponseWriter, modelAlias string) (TokenUsage, error) {
	fl, ok := w.(http.Flusher)
	if !ok {
		return TokenUsage{EstimateOnly: true}, fmt.Errorf("response writer does not flush")
	}
	id := "chatcmpl-bedrock"
	created := time.Now().Unix()
	var emitted bool
	var streamFinished bool
	for {
		if err := ctx.Err(); err != nil {
			return streamAbort(emitted, 0, 0, err)
		}
		ev, err := bedrockstream.ReadEvent(r)
		if err != nil {
			if err == io.EOF {
				if emitted && !streamFinished {
					return streamAbort(emitted, 0, 0, io.ErrUnexpectedEOF)
				}
				break
			}
			return streamAbort(emitted, 0, 0, err)
		}
		if ev.Headers[":message-type"] == "exception" {
			return streamAbort(emitted, 0, 0, fmt.Errorf("bedrock stream exception"))
		}
		parsed, err := bedrockstream.ParseConversePayload(ev.Payload)
		if err != nil {
			continue
		}
		if _, ok := parsed["messageStop"]; ok {
			streamFinished = true
		}
		text := bedrockstream.ExtractDelta(parsed)
		deltaObj := map[string]any{}
		if text != "" {
			deltaObj["content"] = text
		}
		if tool := bedrockstream.ExtractToolUseDelta(parsed); tool != "" {
			deltaObj["tool_calls"] = []map[string]any{{"function": map[string]any{"arguments": tool}}}
		}
		if len(deltaObj) == 0 {
			continue
		}
		delta, _ := json.Marshal(deltaObj)
		chunk := openai.ChatCompletionChunk{ID: id, Object: "chat.completion.chunk", Created: created, Model: modelAlias}
		chunk.Choices = append(chunk.Choices, openai.ChatChunkChoice{Index: 0, Delta: delta})
		if err := WriteOpenAIChunk(w, fl, chunk); err != nil {
			return streamAbort(true, 0, 0, err)
		}
		emitted = true
	}
	return streamComplete(w, fl, 0, 0)
}

func streamAbort(emitted bool, prompt, completion int64, err error) (TokenUsage, error) {
	u := TokenUsage{PromptTokens: prompt, CompletionTokens: completion, EstimateOnly: prompt == 0 && completion == 0}
	if err == nil {
		err = io.ErrUnexpectedEOF
	}
	return u, err
}

func streamComplete(w http.ResponseWriter, fl http.Flusher, prompt, completion int64) (TokenUsage, error) {
	if _, err := io.WriteString(w, "data: [DONE]\n\n"); err != nil {
		return TokenUsage{EstimateOnly: true}, err
	}
	fl.Flush()
	u := TokenUsage{PromptTokens: prompt, CompletionTokens: completion}
	if u.PromptTokens == 0 && u.CompletionTokens == 0 {
		u.EstimateOnly = true
	}
	return u, nil
}
