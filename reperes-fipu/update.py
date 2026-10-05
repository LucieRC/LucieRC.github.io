"""Collecte les données puis régénère la page : python3 update.py"""
import build
import fetch


def run(progress=print):
    data = fetch.run_all(progress=progress)
    build.main()
    return data


if __name__ == "__main__":
    run()
