import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts import backup


class Command(BaseCommand):
    help = "Резервная копия БД + автоматическая проверка копии + удаление старых копий."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(Path(settings.BASE_DIR) / "backups"))
        parser.add_argument("--keep", type=int, default=14, help="сколько последних копий хранить")

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        engine = db["ENGINE"]
        out_dir = Path(opts["dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(out_dir, 0o700)
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        try:
            if "sqlite3" in engine:
                path = out_dir / f"depter-{stamp}.sqlite3"
                backup.backup_sqlite(str(db["NAME"]), str(path))
                rows = backup.verify_sqlite(str(path))
                self.stdout.write(f"проверка копии: целостность ok, операций в копии: {rows}")
            elif "postgresql" in engine:
                path = out_dir / f"depter-{stamp}.dump"
                backup.backup_postgres(db, path)
                backup.verify_postgres(db, path)
                self.stdout.write("проверка копии: pg_restore --list ok")
            else:
                raise CommandError(f"Неподдерживаемая БД: {engine}")
        except backup.BackupError as e:
            raise CommandError(f"Бэкап НЕ удался: {e}")
        os.chmod(path, 0o600)
        (Path(str(path) + ".sha256")).write_text(f"{backup.sha256_of(path)}  {path.name}\n")
        backup.prune(out_dir, opts["keep"])
        self.stdout.write(self.style.SUCCESS(f"Бэкап готов: {path}"))
        self.stdout.write("Скопируйте папку backups/ на другой сервер/диск: копия на той же машине не защищает от её потери.")
