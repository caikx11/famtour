@echo off
rem Abre o Claude Code passando pelo hub (Claude ou modelo local, conforme o painel)
set ANTHROPIC_BASE_URL=http://localhost:4000
claude %*
