.PHONY: help up down build logs migrate shell test smoke loadtest psql redis-cli minio-ui mailhog clean

.DEFAULT_GOAL := help

help: ## 显示此帮助
	@awk 'BEGIN {FS = ":.*##"; printf "\n非遗泥塑工坊系统 · Makefile 命令\n\n使用: make <命令>\n\n命令列表:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ 生命周期管理

up: ## 一键启动全栈服务（docker-compose up -d）
	docker compose up -d --build

down: ## 停止并移除容器（保留数据卷）
	docker compose down

clean: ## 彻底清理（含数据卷！危险！）
	docker compose down -v --remove-orphans

build: ## 仅构建镜像
	docker compose build

logs: ## 实时查看所有服务日志
	docker compose logs -f --tail=200

migrate: ## 执行 Alembic 数据库迁移（容器内）
	docker compose exec api alembic upgrade head

shell: ## 进入 API 容器交互式 Shell
	docker compose exec api bash

##@ 数据库 & 中间件

psql: ## 进入 PostgreSQL CLI
	docker compose exec postgres psql -U clayworkshop -d clayworkshop

redis-cli: ## 进入 Redis CLI
	docker compose exec redis redis-cli

minio-ui: ## 打印 MinIO 控制台地址
	@echo "MinIO Console:  http://localhost:9001"
	@echo "    User: minioadmin   Pass: minioadmin123"

mailhog: ## 打印 MailHog Web 邮件地址
	@echo "MailHog (邮件预览): http://localhost:8025"

##@ 测试

smoke: ## 运行冒烟测试（14步完整业务流程）
	@echo "等待 API 就绪 (http://localhost:8000/health) ..."
	@timeout 60 sh -c 'until curl -sf http://localhost:8000/health >/dev/null 2>&1; do sleep 2; done' && echo "API ready!"
	python tests/smoke_test.py

loadtest: ## 运行 45 并发创建预约压测
	pip install aiohttp >/dev/null 2>&1 || true
	python tests/load_test_45_concurrent.py
	@echo "\n📊 报告文件: tests/load_test_report.json"

##@ 文档

openapi: ## 打印 OpenAPI 文档地址
	@echo "Swagger UI:  http://localhost:8000/docs"
	@echo "ReDoc:       http://localhost:8000/redoc"
	@echo "OpenAPI JSON: http://localhost:8000/openapi.json"
