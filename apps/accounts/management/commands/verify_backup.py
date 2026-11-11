from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts import backup


class Command(BaseCommand):
    help = "Проверка файла копии: контрольная сумма и чтение данных. --restore-test для Postgres восстанавливает во временную БД."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--restore-test", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError(f"Нет файла {path}")
        sum_file = Path(str(path) + ".sha256")
        if sum_file.exists():
            expected = sum_file.read_text().split()[0]
            if backup.sha256_of(path) != expected:
                raise CommandError("Контрольная сумма не совпадает: копия повреждена")
            self.stdout.write("контрольная сумма: ok")
        db = settings.DATABASES["default"]
        try:
            if path.suffix == ".sqlite3":
                rows = backup.verify_sqlite(str(path))
            elif path.suffix == ".dump":
                rows = backup.verify_postgres(db, path, restore_test=opts["restore_test"])
            else:
                raise CommandError("Неизвестный тип копии")
        except backup.BackupError as e:
            raise CommandError(f"Копия НЕ годна: {e}")
        if rows is not None:
            self.stdout.write(f"операций в копии: {rows}")
        self.stdout.write(self.style.SUCCESS("Копия годна для восстановления"))
