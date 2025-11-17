# Input variable for AWS region
variable "aws_region" {
  description = "The AWS region where the S3 bucket will be created"
  type        = string
  default     = "us-east-1"
}

# Optional: choose your bucket prefix
variable "bucket_prefix" {
  description = "Prefix for the S3 bucket name"
  type        = string
  default     = "taco-wagon"
}

# Where your app files live relative to THIS module
# (Given your layout, ../app is correct)
variable "app_dir" {
  description = "Path to the local app folder containing python files and datasets"
  type        = string
  default     = "../app"
}
