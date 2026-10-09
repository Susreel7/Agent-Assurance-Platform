package normalize

import (
	"encoding/json"

	"agent-assurance/services/gateway/internal/openai"
)

func FormatUpstreamError(status int, typ, message, code string) ([]byte, int) {
	body, _ := json.Marshal(openai.ErrorResponse{
		Error: openai.ErrorBody{Message: message, Type: typ, Code: &code},
	})
	return body, status
}

func UnsupportedParam(name string) error {
	return &ParamError{Param: name}
}

type ParamError struct {
	Param string
}

func (e *ParamError) Error() string {
	return "unsupported parameter " + e.Param + " for this provider"
}
