package audit

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

type Exporter struct {
	Queue         *Queue
	URL           string
	Authorization string
	Client        *http.Client
	BatchSize     int
}

type record struct {
	EventType   string         `json:"event_type"`
	Category    string         `json:"category"`
	Severity    string         `json:"severity"`
	Outcome     string         `json:"outcome"`
	ActorKind   string         `json:"actor_kind"`
	ActorID     string         `json:"actor_id,omitempty"`
	ActorLabel  string         `json:"actor_label"`
	TargetKind  string         `json:"target_kind,omitempty"`
	TargetID    string         `json:"target_id,omitempty"`
	TargetLabel string         `json:"target_label,omitempty"`
	ReasonCode  string         `json:"reason_code,omitempty"`
	RequestID   string         `json:"request_id,omitempty"`
	TraceID     string         `json:"trace_id,omitempty"`
	Detail      map[string]any `json:"detail"`
}

func (e *Exporter) Run(ctx context.Context, interval time.Duration) {
	if strings.TrimSpace(e.URL) == "" || strings.TrimSpace(e.Authorization) == "" {
		return
	}
	if interval < 100*time.Millisecond {
		interval = time.Second
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := e.Flush(ctx); err != nil {
				// The data plane never blocks on audit delivery. The queue keeps the batch
				// for retry and exposes overflow through Queue.Drops().
				continue
			}
		}
	}
}

func (e *Exporter) Flush(ctx context.Context) error {
	if strings.TrimSpace(e.URL) == "" || strings.TrimSpace(e.Authorization) == "" {
		return nil
	}
	batchSize := e.BatchSize
	if batchSize < 1 || batchSize > 1000 {
		batchSize = 500
	}
	events := e.Queue.Drain(batchSize)
	if len(events) == 0 {
		return nil
	}
	payload := make([]record, len(events))
	for i, event := range events {
		payload[i] = toRecord(event)
	}
	body, err := json.Marshal(payload)
	if err != nil {
		e.Queue.Requeue(events)
		return fmt.Errorf("encode audit batch: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.URL, bytes.NewReader(body))
	if err != nil {
		e.Queue.Requeue(events)
		return fmt.Errorf("create audit request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	authorization := strings.TrimSpace(e.Authorization)
	if !strings.HasPrefix(strings.ToLower(authorization), "bearer ") {
		authorization = "Bearer " + authorization
	}
	req.Header.Set("Authorization", authorization)
	client := e.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	response, err := client.Do(req)
	if err != nil {
		e.Queue.Requeue(events)
		return fmt.Errorf("send audit batch: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		e.Queue.Requeue(events)
		return fmt.Errorf("audit endpoint returned %d", response.StatusCode)
	}
	return nil
}

func toRecord(event Event) record {
	category := "routing"
	severity := "info"
	eventType := "gateway.routing.allowed"
	outcome := "allowed"
	if event.Outcome != "success" {
		outcome = "failed"
		severity = "warning"
		eventType = "gateway.routing.failed"
	}
	if event.Outcome == "denied" {
		outcome = "denied"
		eventType = "gateway.routing.denied"
	}
	if event.ReasonCode == "secret_detected" || event.ReasonCode == "secret_detected_audit" {
		category = "data"
		severity = "critical"
		eventType = "gateway.data.secret_detected"
		if event.Outcome == "success" {
			outcome = "allowed"
		}
	}

	actorKind := "workload"
	actorID := ""
	actorLabel := "gateway workload"
	if event.AgentID != "" {
		actorKind = "agent"
		actorID = event.AgentID
		actorLabel = "agent:" + event.AgentID
	}
	if event.MemberID != "" {
		actorKind = "member"
		actorID = event.MemberID
		actorLabel = "member:" + event.MemberID
	}

	targetKind := ""
	targetID := ""
	targetLabel := ""
	if event.RouteID != "" {
		targetKind = "model_route"
		targetID = event.RouteID
		targetLabel = event.ModelAlias
	} else if event.DeploymentID != "" {
		targetKind = "model_deployment"
		targetID = event.DeploymentID
		targetLabel = event.ModelAlias
	}
	detail := map[string]any{
		"project_id":      event.ProjectID,
		"environment":     event.Environment,
		"operation":       bounded(event.Operation, 512),
		"model_alias":     bounded(event.ModelAlias, 512),
		"provider":        bounded(event.Provider, 512),
		"deployment_id":   event.DeploymentID,
		"http_status":     event.HTTPStatus,
		"attempts":        event.Attempts,
		"retry_count":     event.RetryCount,
		"ttfb_ms":         event.TTFBMs,
		"overhead_ms":     event.OverheadMs,
		"finding_kinds":   strings.Join(event.FindingKinds, ","),
	}
	return record{
		EventType:   eventType,
		Category:    category,
		Severity:    severity,
		Outcome:     outcome,
		ActorKind:   actorKind,
		ActorID:     actorID,
		ActorLabel:  actorLabel,
		TargetKind:  targetKind,
		TargetID:    targetID,
		TargetLabel: bounded(targetLabel, 256),
		ReasonCode:  event.ReasonCode,
		RequestID:   bounded(event.IdempotencyKey, 128),
		TraceID:     traceID(event.TraceParent),
		Detail:      detail,
	}
}

func bounded(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit]
}

func traceID(traceparent string) string {
	parts := strings.Split(traceparent, "-")
	if len(parts) == 4 && len(parts[1]) == 32 {
		return parts[1]
	}
	return ""
}
