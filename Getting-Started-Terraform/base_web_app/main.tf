terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region            = var.aws_region
  s3_use_path_style = true
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

# --- S3 module (relative to base_web_app/) ---
module "s3" {
  source        = "../s3_bucket_create"
  aws_region    = var.aws_region
  bucket_prefix = "taco-wagon"
}

# --- EC2 module (relative to base_web_app/) ---
module "ec2" {
  source            = "../ec2"
  aws_region        = var.aws_region
  http_port         = 80
  ec2_instance_type = "t3.medium"   # <-- au lieu de t3.micro
  bucket_name       = module.s3.bucket_name
}


# Helpful outputs
output "bucket_name" { value = module.s3.bucket_name }
output "app_url" { value = "http://${module.ec2.aws_instance_public_dns}/" }
output "api_docs_url" { value = "http://${module.ec2.aws_instance_public_dns}/api/docs" }

# NEW: network IDs from ec2 module
output "vpc_id" {
  description = "ID of the created VPC"
  value       = module.ec2.vpc_id
}

output "public_subnet_id" {
  description = "ID of the public subnet"
  value       = module.ec2.public_subnet_id
}
