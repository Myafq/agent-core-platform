locals {
  common_tags = merge(var.tags, { Component = "container-registry" })
}

resource "aws_ecr_repository" "this" {
  for_each             = var.repositories
  name                 = each.value
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = var.repositories
  repository = aws_ecr_repository.this[each.key].name
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Retain the ten newest images"
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
    action       = { type = "expire" }
  }] })
}
