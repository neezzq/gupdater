# Навыки Claude Code для GUpdater

Взяты из открытого набора [obra/superpowers](https://github.com/obra/superpowers)
(коммит 22f0b46, лицензия MIT, см. `LICENSE-superpowers`). Ссылки вида
`superpowers:имя` заменены на имена навыков в этой папке, остальное без изменений.

- `systematic-debugging/`: сначала найти причину ошибки, потом чинить.
- `test-driven-development/`: тест пишется до кода. Примеры в нём на TypeScript,
  у нас тесты запускаются командой `python -m pytest`.
- `verification-before-completion/`: не говорить «готово», пока проверка не прошла.
