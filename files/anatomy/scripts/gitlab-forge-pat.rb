# gitlab-forge-pat.rb — mint the nOS agent-forge PAT with a KNOWN value.
# Run inside the GitLab container:  gitlab-rails runner -  (script via stdin;
# values via env — docker compose exec -e VAR pass-through keeps them out of
# argv/ps). Invoked by roles/pazny.gitlab/tasks/post-forge.yml.
# NO Ruby string interpolation (the escaped-quote-inside-interpolation trap
# silently SyntaxError'd the root-pw reconverge for weeks) — concat only.
user = User.find_by(username: ENV.fetch("NOS_FORGE_OWNER"))
abort("ERROR: forge user not found") if user.nil?
name = ENV.fetch("NOS_FORGE_TOKEN_NAME")
PersonalAccessToken.where(user: user, name: name).find_each do |t|
  t.revoke! unless t.revoked?
end
scopes = ENV.fetch("NOS_FORGE_SCOPES").split(",")
t = user.personal_access_tokens.create(scopes: scopes, name: name, expires_at: 364.days.from_now)
t.set_token(ENV.fetch("NOS_FORGE_PAT"))
if t.save
  puts "CREATED"
else
  puts "ERROR: " + t.errors.full_messages.join(", ")
end
