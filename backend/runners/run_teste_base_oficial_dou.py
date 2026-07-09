import requests
import datetime

DATA = datetime.date(2026, 4, 1)

def buscar_base_dou(data: datetime.date):
    data_str = data.strftime("%d-%m-%Y")

    url = (
        "https://www.in.gov.br/leiturajornal"
        f"?data={data_str}&secao=do1"
    )

    print(f"Buscando DOU oficial: {url}")

    response = requests.get(url)

    if response.status_code != 200:
        raise Exception(f"Erro ao acessar DOU: {response.status_code}")

    return response.json()


def main():
    data = DATA

    dados = buscar_base_dou(data)

    total = len(dados.get("items", []))

    print("=" * 80)
    print(f"DATA: {data}")
    print(f"TOTAL PUBLICAÇÕES: {total}")
    print("=" * 80)

    # Mostrar alguns exemplos
    for item in dados.get("items", [])[:5]:
        print(item.get("titulo"))
        print(item.get("orgao"))
        print("-" * 50)


if __name__ == "__main__":
    main()