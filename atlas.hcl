env "local" {
  src = "file://migrations"
  url = "postgres://orchestack:orchestack-dev@localhost:5432/orchestack?sslmode=disable"
  dev = "docker://postgres/16/dev?search_path=public"
}
