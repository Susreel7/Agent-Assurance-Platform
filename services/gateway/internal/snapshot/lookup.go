package snapshot

func (s *ActivatedSnapshot) BindingByGeneration(generationID string) (WorkloadBinding, bool) {
	for _, b := range s.Config.WorkloadBindings {
		if b.GenerationID == generationID {
			return b, true
		}
	}
	return WorkloadBinding{}, false
}
