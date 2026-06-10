# gitlab-root-password.rb — reconverge the GitLab root password from
# credentials.yml. Run inside the GitLab container via gitlab-rails runner -
# (stdin; password via env pass-through, never argv). Invoked by
# roles/pazny.gitlab/tasks/post.yml.
# Concat (not interpolation) for the error line — see gitlab-forge-pat.rb.
user = User.find_by(username: "root")
if user.nil?
  puts "ERROR: root user not found"
  exit 1
end
pw = ENV.fetch("NOS_GITLAB_ROOT_PW")
user.password = pw
user.password_confirmation = pw
user.password_automatically_set = false
if user.save
  puts "UPDATED"
else
  puts "ERROR: " + user.errors.full_messages.join(", ")
end
