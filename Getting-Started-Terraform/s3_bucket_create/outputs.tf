# Bucket name/ID/ARN for wiring the EC2 role later
output "bucket_name" {
  description = "The name of the created S3 bucket"
  value       = aws_s3_bucket.taco_wagon.bucket
}

output "bucket_id" {
  description = "Same as name but typed as ID"
  value       = aws_s3_bucket.taco_wagon.id
}

output "bucket_arn" {
  description = "Bucket ARN"
  value       = aws_s3_bucket.taco_wagon.arn
}

# Region used
output "bucket_region" {
  description = "The AWS region where the bucket was created"
  value       = var.aws_region
}
