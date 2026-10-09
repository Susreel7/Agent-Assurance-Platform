package router

import (
	"math/rand"
	"sort"
	"time"

	"agent-assurance/services/gateway/internal/limiter"
	"agent-assurance/services/gateway/internal/snapshot"
)

type Candidate struct {
	Deployment snapshot.Deployment
	Score      float64
}

type Selector struct {
	Local  limiter.LocalLimiter
	Health *HealthRegistry
	RNG    *rand.Rand
}

func NewSelector(local limiter.LocalLimiter) *Selector {
	return &Selector{Local: local, Health: NewHealthRegistry(), RNG: rand.New(rand.NewSource(time.Now().UnixNano()))}
}

func FilterDeployments(
	snap *snapshot.ActivatedSnapshot,
	route snapshot.Route,
	op string,
	dataClass string,
	regionHint string,
) []snapshot.Deployment {
	out := make([]snapshot.Deployment, 0, len(route.DeploymentIDs))
	permRegions := toSet(route.PermittedRegions)
	dataClasses := toSet(route.DataClasses)
	for _, id := range route.DeploymentIDs {
		d, ok := snap.ByDeploy[id]
		if !ok {
			continue
		}
		if !hasCapability(d, op) {
			continue
		}
		if len(permRegions) > 0 {
			if _, ok := permRegions[d.Region]; !ok {
				continue
			}
		}
		if regionHint != "" && d.Region != regionHint {
			continue
		}
		if len(dataClasses) > 0 && len(d.DataClasses) > 0 {
			if !intersects(dataClasses, toSet(d.DataClasses)) {
				continue
			}
		}
		if dataClass != "" && len(d.DataClasses) > 0 {
			if _, ok := toSet(d.DataClasses)[dataClass]; !ok {
				continue
			}
		}
		out = append(out, d)
	}
	return out
}

func (s *Selector) Order(route snapshot.Route, candidates []snapshot.Deployment) []Candidate {
	if len(candidates) == 0 {
		return nil
	}
	now := time.Now().UTC()
	avail := make([]snapshot.Deployment, 0, len(candidates))
	for _, c := range candidates {
		if s.Health != nil && !s.Health.Available(c, now) {
			continue
		}
		avail = append(avail, c)
	}
	if len(avail) == 0 {
		avail = candidates
	}
	switch route.Strategy {
	case "priority":
		sort.Slice(avail, func(i, j int) bool {
			if avail[i].Priority == avail[j].Priority {
				return avail[i].ID < avail[j].ID
			}
			return avail[i].Priority < avail[j].Priority
		})
		return singleOrder(avail)
	case "weighted":
		shuffled := weightedShuffle(s.RNG, avail)
		return singleOrder(shuffled)
	case "least_busy":
		sort.Slice(avail, func(i, j int) bool {
			return s.Local.BusyCount(avail[i].ID) < s.Local.BusyCount(avail[j].ID)
		})
		return singleOrder(avail)
	case "latency":
		type scored struct {
			d snapshot.Deployment
			v float64
		}
		sc := make([]scored, len(avail))
		for i, c := range avail {
			v := s.Local.LatencyEWMA(c.ID)
			if s.Health != nil {
				if ew := s.Health.EWMA(c.ID); ew > 0 {
					v = ew
				}
			}
			sc[i] = scored{d: c, v: v}
		}
		sort.Slice(sc, func(i, j int) bool {
			if sc[i].v == sc[j].v {
				return sc[i].d.ID < sc[j].d.ID
			}
			return sc[i].v < sc[j].v
		})
		out := make([]Candidate, len(sc))
		for i, x := range sc {
			out[i] = Candidate{Deployment: x.d, Score: x.v}
		}
		return out
	case "lowest_cost":
		sort.Slice(avail, func(i, j int) bool {
			ci := depUnitCost(avail[i])
			cj := depUnitCost(avail[j])
			if ci == cj {
				return avail[i].ID < avail[j].ID
			}
			return ci < cj
		})
		return singleOrder(avail)
	default:
		return singleOrder(avail)
	}
}

func depUnitCost(d snapshot.Deployment) int64 {
	return d.InputPriceMicrosPerM + d.OutputPriceMicrosPerM
}

func weightedShuffle(rng *rand.Rand, candidates []snapshot.Deployment) []snapshot.Deployment {
	remaining := append([]snapshot.Deployment(nil), candidates...)
	out := make([]snapshot.Deployment, 0, len(candidates))
	for len(remaining) > 0 {
		total := 0
		for _, c := range remaining {
			w := c.Weight
			if w < 1 {
				w = 1
			}
			total += w
		}
		pick := rng.Intn(total)
		acc := 0
		idx := 0
		for i, c := range remaining {
			w := c.Weight
			if w < 1 {
				w = 1
			}
			acc += w
			if pick < acc {
				idx = i
				break
			}
		}
		out = append(out, remaining[idx])
		remaining = append(remaining[:idx], remaining[idx+1:]...)
	}
	return out
}

func singleOrder(deps []snapshot.Deployment) []Candidate {
	out := make([]Candidate, len(deps))
	for i, d := range deps {
		out[i] = Candidate{Deployment: d, Score: float64(d.Priority)}
	}
	return out
}

func hasCapability(d snapshot.Deployment, op string) bool {
	need := op
	switch op {
	case "chat", "responses":
		need = op
	case "embeddings":
		need = "embeddings"
	}
	for _, c := range d.Capabilities {
		if c == need {
			return true
		}
	}
	return false
}

func toSet(items []string) map[string]struct{} {
	m := make(map[string]struct{}, len(items))
	for _, v := range items {
		m[v] = struct{}{}
	}
	return m
}

func intersects(a, b map[string]struct{}) bool {
	for k := range a {
		if _, ok := b[k]; ok {
			return true
		}
	}
	return false
}
