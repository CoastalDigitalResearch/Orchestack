env "local" {
  src = "file://schema.sql"
  url = "postgresql://orchestack:orchestack-dev@localhost:5432/orchestack?sslmode=disable"
  dev = "docker://postgres/16/dev"

  migration {
    dir = "file://migrations"
  }
}

env "prod" {
  src = "file://schema.sql"

  migration {
    dir = "file://migrations"
  }
}
