"""Collecte les sources puis régénère la page : python3 update.py"""
import build
import fetch


def run(progress=print):
    result = fetch.run_all(progress=progress)
    build.main()
    return result


if __name__ == "__main__":
    run()
