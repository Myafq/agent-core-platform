output "private_subnet_ids" {
  description = "Private subnets spanning the EFS mount-target Availability Zones."
  value       = [for availability_zone in sort(keys(aws_subnet.private)) : aws_subnet.private[availability_zone].id]
}

output "runtime_security_group_id" {
  description = "Security group for the Harness VPC environment."
  value       = aws_security_group.runtime.id
}

output "efs_access_point_arn" {
  value = aws_efs_access_point.workspace.arn
}

output "efs_file_system_arn" {
  value = aws_efs_file_system.this.arn
}
