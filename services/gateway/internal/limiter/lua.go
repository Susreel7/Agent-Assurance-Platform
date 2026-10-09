package limiter

// acquireScript atomically checks org, credential, and deployment tiers; rolls back all prior tiers on denial.
const acquireScript = `
local function tier_apply(conc_key, rpm_key, tpm_key, budget_key, max_conc, rpm_lim, tpm_lim, budget_lim, tokens, cost, rpm_ttl, budget_ttl)
  local st = {conc=false, rpm=false, tpm=0, budget=0}
  if max_conc > 0 then
    local c = redis.call('INCR', conc_key)
    if c == 1 then redis.call('EXPIRE', conc_key, 3600) end
    if c > max_conc then
      redis.call('DECR', conc_key)
      return st, false
    end
    st.conc = true
  end
  if rpm_lim > 0 then
    local r = redis.call('INCR', rpm_key)
    if r == 1 then redis.call('EXPIRE', rpm_key, rpm_ttl) end
    if r > rpm_lim then
      if st.conc then redis.call('DECR', conc_key) end
      return st, false
    end
    st.rpm = true
  end
  if tpm_lim > 0 then
    local t = redis.call('INCRBY', tpm_key, tokens)
    if t == tokens then redis.call('EXPIRE', tpm_key, rpm_ttl) end
    if t > tpm_lim then
      if st.rpm then redis.call('DECR', rpm_key) end
      if st.conc then redis.call('DECR', conc_key) end
      return st, false
    end
    st.tpm = tokens
  end
  if budget_lim > 0 then
    local b = redis.call('INCRBY', budget_key, cost)
    if b == cost then redis.call('EXPIRE', budget_key, budget_ttl) end
    if b > budget_lim then
      if st.tpm > 0 then redis.call('DECRBY', tpm_key, st.tpm) end
      if st.rpm then redis.call('DECR', rpm_key) end
      if st.conc then redis.call('DECR', conc_key) end
      return st, false
    end
    st.budget = cost
  end
  return st, true
end
local function tier_rollback(conc_key, rpm_key, tpm_key, budget_key, st)
  if st.budget > 0 then redis.call('DECRBY', budget_key, st.budget) end
  if st.tpm > 0 then redis.call('DECRBY', tpm_key, st.tpm) end
  if st.rpm then redis.call('DECR', rpm_key) end
  if st.conc then redis.call('DECR', conc_key) end
end
local tokens = tonumber(ARGV[13])
local cost = tonumber(ARGV[14])
local rpm_ttl = tonumber(ARGV[15])
local budget_ttl = tonumber(ARGV[16])
local tiers = {
  {KEYS[1], KEYS[2], KEYS[3], KEYS[4], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])},
  {KEYS[5], KEYS[6], KEYS[7], KEYS[8], tonumber(ARGV[5]), tonumber(ARGV[6]), tonumber(ARGV[7]), tonumber(ARGV[8])},
  {KEYS[9], KEYS[10], KEYS[11], KEYS[12], tonumber(ARGV[9]), tonumber(ARGV[10]), tonumber(ARGV[11]), tonumber(ARGV[12])},
}
local applied = {}
for i, t in ipairs(tiers) do
  local st, ok = tier_apply(t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], tokens, cost, rpm_ttl, budget_ttl)
  if not ok then
    for j = i - 1, 1, -1 do
      local u = applied[j]
      tier_rollback(u[1], u[2], u[3], u[4], u[5])
    end
    return 0
  end
  applied[i] = {t[1], t[2], t[3], t[4], st}
end
return 1
`

const releaseScript = `
local function release_tier(conc_key, tpm_key, budget_key, token_adj, cost_adj)
  if redis.call('EXISTS', conc_key) == 1 then redis.call('DECR', conc_key) end
  if token_adj ~= 0 and redis.call('EXISTS', tpm_key) == 1 then redis.call('INCRBY', tpm_key, token_adj) end
  if cost_adj ~= 0 and redis.call('EXISTS', budget_key) == 1 then redis.call('INCRBY', budget_key, cost_adj) end
end
local token_adj = tonumber(ARGV[1])
local cost_adj = tonumber(ARGV[2])
release_tier(KEYS[1], KEYS[2], KEYS[3], token_adj, cost_adj)
release_tier(KEYS[4], KEYS[5], KEYS[6], token_adj, cost_adj)
release_tier(KEYS[7], KEYS[8], KEYS[9], token_adj, cost_adj)
return 1
`

func tierKeys(prefix, minute, day string) []string {
	return []string{prefix + ":conc", prefix + ":rpm:" + minute, prefix + ":tpm:" + minute, prefix + ":budget:" + day}
}

func OrgPrefix(org string) string            { return "gw:o:" + HashKey(org) }
func CredPrefix(org, cred string) string     { return "gw:c:" + HashKey(org, cred) }
func DepPrefix(org, cred, dep string) string { return "gw:d:" + HashKey(org, cred, dep) }
