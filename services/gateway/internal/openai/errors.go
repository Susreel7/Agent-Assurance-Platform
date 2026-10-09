package openai

import (
	"encoding/json"
	"net/http"
)

// ErrorResponse is the OpenAI-compatible error envelope.
type ErrorResponse struct {
	Error ErrorBody `json:"error"`
}

type ErrorBody struct {
	Message string  `json:"message"`
	Type    string  `json:"type"`
	Param   *string `json:"param,omitempty"`
	Code    *string `json:"code,omitempty"`
}

func WriteError(w http.ResponseWriter, status int, typ, message, code string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	c := code
	_ = json.NewEncoder(w).Encode(ErrorResponse{
		Error: ErrorBody{
			Message: message,
			Type:    typ,
			Code:    &c,
		},
	})
}

const (
	TypeInvalidRequest = "invalid_request_error"
	TypeAuth           = "authentication_error"
	TypePermission     = "permission_error"
	TypeNotFound       = "invalid_request_error"
	TypeRateLimit      = "rate_limit_error"
	TypeServer         = "server_error"
)
