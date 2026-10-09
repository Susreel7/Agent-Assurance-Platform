package provider

import "agent-assurance/services/gateway/internal/normalize"

type DeliveryResult struct {
	Usage        normalize.TokenUsage
	ResponseBody []byte
	Status       int
	Cacheable    bool
}
