package audit

import (
	"context"
	"sync"
	"time"
)

// Event contains routing metadata only — no prompts, secrets, or payloads.
type Event struct {
	OccurredAt     time.Time `json:"occurred_at"`
	OrganizationID string    `json:"organization_id"`
	ProjectID      string    `json:"project_id"`
	AgentID        string    `json:"agent_id,omitempty"`
	MemberID       string    `json:"member_id,omitempty"`
	Environment    string    `json:"environment,omitempty"`
	RouteID        string    `json:"route_id,omitempty"`
	DeploymentID   string    `json:"deployment_id,omitempty"`
	Provider       string    `json:"provider,omitempty"`
	ModelAlias     string    `json:"model_alias,omitempty"`
	Operation      string    `json:"operation"`
	Outcome        string    `json:"outcome"`
	ReasonCode     string    `json:"reason_code,omitempty"`
	FindingKinds   []string  `json:"finding_kinds,omitempty"`
	HTTPStatus     int       `json:"http_status"`
	Attempts       int       `json:"attempts"`
	RetryCount     int       `json:"retry_count"`
	TTFBMs         int64     `json:"ttfb_ms,omitempty"`
	OverheadMs     int64     `json:"overhead_ms"`
	TraceParent    string    `json:"traceparent,omitempty"`
	IdempotencyKey string    `json:"idempotency_key,omitempty"`
}

type Queue struct {
	ch     chan Event
	dropMu sync.Mutex
	drops  uint64
}

func NewQueue(capacity int) *Queue {
	if capacity < 1 {
		capacity = 1024
	}
	return &Queue{ch: make(chan Event, capacity)}
}

func (q *Queue) Enqueue(ctx context.Context, ev Event) {
	select {
	case q.ch <- ev:
	case <-ctx.Done():
	default:
		q.dropMu.Lock()
		q.drops++
		q.dropMu.Unlock()
	}
}

func (q *Queue) Drops() uint64 {
	q.dropMu.Lock()
	defer q.dropMu.Unlock()
	return q.drops
}

func (q *Queue) Pending() int {
	return len(q.ch)
}

func (q *Queue) Drain(max int) []Event {
	out := make([]Event, 0, max)
	for i := 0; i < max; i++ {
		select {
		case ev := <-q.ch:
			out = append(out, ev)
		default:
			return out
		}
	}
	return out
}

// Requeue returns an unsent batch after a transient exporter failure. It is intentionally
// bounded by the same channel capacity: data-plane availability wins over blocking model
// requests, while Drops makes any loss externally visible.
func (q *Queue) Requeue(events []Event) {
	for _, ev := range events {
		select {
		case q.ch <- ev:
		default:
			q.dropMu.Lock()
			q.drops++
			q.dropMu.Unlock()
		}
	}
}
