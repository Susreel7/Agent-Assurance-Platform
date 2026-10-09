package audit

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestExporterUsesMemberAsAuditActor(t *testing.T) {
	var got []record
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Authorization") != "Bearer test-token" {
			t.Fatalf("unexpected authorization header")
		}
		if err := json.NewDecoder(request.Body).Decode(&got); err != nil {
			t.Fatalf("decode: %v", err)
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()

	queue := NewQueue(4)
	queue.Enqueue(context.Background(), Event{
		Outcome:      "success",
		MemberID:     "00000000-0000-0000-0000-000000000001",
		AgentID:      "00000000-0000-0000-0000-000000000002",
		RouteID:      "00000000-0000-0000-0000-000000000003",
		ModelAlias:   "approved-chat",
		TraceParent:  "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
		HTTPStatus:   http.StatusOK,
		DeploymentID: "00000000-0000-0000-0000-000000000004",
	})
	exporter := &Exporter{
		Queue:         queue,
		URL:           server.URL,
		Authorization: "test-token",
	}

	if err := exporter.Flush(context.Background()); err != nil {
		t.Fatalf("flush: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("got %d records", len(got))
	}
	if got[0].ActorKind != "member" || got[0].ActorID != "00000000-0000-0000-0000-000000000001" {
		t.Fatalf("unexpected actor: %#v", got[0])
	}
	if got[0].TraceID != "0123456789abcdef0123456789abcdef" {
		t.Fatalf("unexpected trace id: %q", got[0].TraceID)
	}
	if queue.Pending() != 0 {
		t.Fatalf("queue was not drained")
	}
}

func TestExporterRequeuesFailedBatch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer server.Close()

	queue := NewQueue(4)
	queue.Enqueue(context.Background(), Event{Outcome: "denied", ReasonCode: "policy_denied"})
	exporter := &Exporter{Queue: queue, URL: server.URL, Authorization: "Bearer test-token"}

	if err := exporter.Flush(context.Background()); err == nil {
		t.Fatal("expected failed export")
	}
	if queue.Pending() != 1 {
		t.Fatalf("failed batch was not requeued")
	}
}
