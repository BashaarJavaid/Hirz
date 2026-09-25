"""Build the pinned reference CLI and private helper; requires Cargo/network."""

import argparse
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

REVISION = "996d756de1013b7ae209a14f566a80375a59f2f0"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".tools/dogwood"))
    args = parser.parse_args()
    lock = Path(__file__).with_name("dogwood.Cargo.lock").resolve()
    with TemporaryDirectory(prefix="hirz-dogwood-build-") as directory:
        root = Path(directory)
        for command in (
            ["git", "init", "--quiet", str(root)],
            [
                "git",
                "-C",
                str(root),
                "fetch",
                "--depth=1",
                "https://github.com/dogwood-policy/dogwood.git",
                REVISION,
            ],
            ["git", "-C", str(root), "checkout", "--detach", "FETCH_HEAD"],
        ):
            subprocess.run(command, check=True)
        shutil.copyfile(lock, root / "Cargo.lock")
        subprocess.run(
            ["cargo", "build", "--locked", "--release", "-p", "dogwood-cli"],
            cwd=root,
            check=True,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / "target/release/dogwood", args.output)
        # Keep the reference CLI unmodified; only the helper uses Clone support.
        subprocess.run(
            ["git", "apply", str(lock.with_name("dogwood-clone.patch"))],
            cwd=root,
            check=True,
        )
        binary = root / "dogwood-cli/src/bin/dogwood-helper.rs"
        binary.parent.mkdir(exist_ok=True)
        shutil.copyfile(lock.with_name("dogwood-helper.rs"), binary)
        subprocess.run(
            ["cargo", "build", "--locked", "--release", "--bin", "dogwood-helper"],
            cwd=root,
            check=True,
        )
        shutil.copy2(
            root / "target/release/dogwood-helper",
            args.output.with_name(args.output.name + "-helper"),
        )
    print(f"Built Dogwood {REVISION} and helper: {args.output.resolve()}")


if __name__ == "__main__":
    main()
