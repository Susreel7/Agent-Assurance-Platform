package provider

import (
	"net/http"

	"agent-assurance/services/gateway/internal/normalize"
)

func DeliverEmbeddingsResult(w http.ResponseWriter, depName string, status int, body []byte, modelAlias string, max int64) (DeliveryResult, error) {
	_ = max
	if status < 200 || status >= 300 {
		err := writeNormalizedError(w, depName, status, body)
		return DeliveryResult{Status: status}, err
	}
	var out []byte
	var err error
	switch depName {
	case "gemini", "vertex":
		out, err = normalize.GeminiEmbeddingsToOpenAI(body, modelAlias)
		if err != nil {
			openaiWrite(w, http.StatusBadGateway, err.Error())
			return DeliveryResult{}, err
		}
	default:
		out = body
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, werr := w.Write(out)
	usage := normalize.UsageFromOpenAIChat(out)
	return DeliveryResult{Usage: usage, ResponseBody: out, Status: http.StatusOK, Cacheable: true}, werr
}
