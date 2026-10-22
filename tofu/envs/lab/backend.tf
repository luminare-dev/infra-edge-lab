# Remote state in the S3-compatible bucket (Cloudflare R2), with OpenTofu's lock file next to
# the state object (use_lockfile) and the state encrypted before upload (encryption.tofu).
# docs/adr/0013 has the reasons. The account-specific endpoint is not in the code: it comes
# from AWS_ENDPOINT_URL_S3 (https://<account_id>.r2.cloudflarestorage.com, or
# https://<account_id>.eu.r2.cloudflarestorage.com for a bucket in the EU jurisdiction), and
# the credentials from AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, all three in
# secrets/lab.enc.env. "task init ENV=lab BACKEND=local" replaces this block with a local state
# file through a git-ignored backend_override.tf.

terraform {
  backend "s3" {
    bucket = "luminare-tfstate"
    key    = "lab/terraform.tfstate"
    region = "auto"

    use_lockfile                = true
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    skip_metadata_api_check     = true
  }
}
