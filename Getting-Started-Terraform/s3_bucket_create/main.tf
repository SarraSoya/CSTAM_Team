# Configure the AWS Provider
provider "aws" {
  region            = var.aws_region
  s3_use_path_style = true
}

# =====================
# S3 bucket
# =====================
resource "aws_s3_bucket" "taco_wagon" {
  bucket_prefix = var.bucket_prefix
  force_destroy = true

  tags = {
    Environment = "terraform-demo"
    Purpose     = "App artifacts and datasets"
  }
}

# Versioning
resource "aws_s3_bucket_versioning" "taco_wagon_versioning" {
  bucket = aws_s3_bucket.taco_wagon.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "taco_wagon_encryption" {
  bucket = aws_s3_bucket.taco_wagon.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ------------------------------------------------------------------
# Public-read policy ONLY for the app/* prefix (no IAM on the EC2)
# ------------------------------------------------------------------
data "aws_iam_policy_document" "public_read_app" {
  statement {
    sid     = "AllowGetObjectForAppPrefix"
    effect  = "Allow"
    actions = ["s3:GetObject"]

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    resources = [
      "${aws_s3_bucket.taco_wagon.arn}/app/*"
    ]
  }
}

resource "aws_s3_bucket_policy" "public_read_app" {
  bucket = aws_s3_bucket.taco_wagon.id
  policy = data.aws_iam_policy_document.public_read_app.json
}

# Block public access (relaxed to allow the policy above)
resource "aws_s3_bucket_public_access_block" "taco_wagon_pab" {
  bucket                  = aws_s3_bucket.taco_wagon.id
  block_public_acls       = false
  ignore_public_acls      = false
  block_public_policy     = false
  restrict_public_buckets = false
}

# =====================================================
# Upload application files and datasets
# Folder layout assumed:
#   ../app/ingestion_api.py
#   ../app/realtime_simulator.py
#   ../app/datasets/*.txt
# =====================================================

# Upload Python files
resource "aws_s3_object" "ingestion_api" {
  bucket       = aws_s3_bucket.taco_wagon.id
  key          = "app/ingestion_api.py"
  source       = "${var.app_dir}/ingestion_api.py"
  etag         = filemd5("${var.app_dir}/ingestion_api.py")
  content_type = "text/x-python"
}

resource "aws_s3_object" "realtime_simulator" {
  bucket       = aws_s3_bucket.taco_wagon.id
  key          = "app/realtime_simulator.py"
  source       = "${var.app_dir}/realtime_simulator.py"
  etag         = filemd5("${var.app_dir}/realtime_simulator.py")
  content_type = "text/x-python"
}

# Upload dataset files (.txt). If you later switch to CSV, change pattern to "*.csv".
locals {
  dataset_files = fileset("${var.app_dir}/datasets", "*.txt")
}

resource "aws_s3_object" "datasets" {
  for_each     = { for f in local.dataset_files : f => f }
  bucket       = aws_s3_bucket.taco_wagon.id
  key          = "app/datasets/${each.value}"
  source       = "${var.app_dir}/datasets/${each.value}"
  etag         = filemd5("${var.app_dir}/datasets/${each.value}")
  content_type = "text/plain"
}
# NEW: data_cleaning.py
resource "aws_s3_object" "data_cleaning" {
  bucket       = aws_s3_bucket.taco_wagon.id
  key          = "app/data_cleaning.py"
  source       = "${var.app_dir}/data_cleaning.py"
  etag         = filemd5("${var.app_dir}/data_cleaning.py")
  content_type = "text/x-python"
}
