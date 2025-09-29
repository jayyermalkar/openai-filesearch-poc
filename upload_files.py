#!/usr/bin/env python3

"""

upload_files.py



This script:

  1) Uses existing files in ./policies directory

  2) Creates an OpenAI vector store

  3) Uploads the files and attaches them to the vector store (embedding + indexing handled by OpenAI)

  4) Saves the vector store ID to disk (store_id.txt) for later querying

"""



import pathlib

from typing import List

from openai import OpenAI



STORE_NAME = "policy-vector-store"

POLICY_DIR = pathlib.Path("./policies")

STORE_ID_FILE = "store_id.txt"





def get_existing_policy_files(base_dir: pathlib.Path) -> List[pathlib.Path]:

    """

    Returns a list of existing policy file paths in the directory.

    """

    if not base_dir.exists() or not base_dir.is_dir():

        raise FileNotFoundError(f"Policy directory {base_dir} does not exist.")

   

    files = [p for p in base_dir.glob("*") if p.is_file()]

    if not files:

        raise FileNotFoundError(f"No files found in {base_dir}.")

    return files





def upload_files_and_attach(client: OpenAI, store_id: str, file_paths: List[pathlib.Path]):

    """

    Uploads each file to OpenAI (Files API) and attaches it to the vector store.

    Returns a list of file IDs added to the store.

    """

    file_ids = []

    for p in file_paths:

        uploaded = client.files.create(file=open(p, "rb"), purpose="assistants")

        file_ids.append(uploaded.id)

        print(f"Uploaded {p.name} as file_id={uploaded.id}")



        _ = client.vector_stores.files.create(

            vector_store_id=store_id,

            file_id=uploaded.id,

        )

        print(f"Attached {p.name} to vector_store_id={store_id}")

    return file_ids





def main():

    # load_dotenv()

   

    # cert = os.path.join(os.path.dirname(__file__), 'Zscaler.cer')

    # os.environ["REQUESTS_CA_BUNDLE"] = cert

    # os.environ["SSL_CERT_FILE"] = cert

    # openai_api_key = os.getenv("OPENAI_API_KEY")

    client = OpenAI()



    # 1) Use existing local policy files

    files = get_existing_policy_files(POLICY_DIR)

    print(f"Found {len(files)} policy files: {[p.name for p in files]}")



    # 2) Create vector store

    store = client.vector_stores.create(name=STORE_NAME)

    store_id = store.id

    print(f"Created vector store: name={store.name} id={store_id}")



    # 3) Upload & attach files

    file_ids = upload_files_and_attach(client, store_id, files)

    print(f"Vector store now has {len(file_ids)} files attached.")



    # 4) Save store_id for querying

    with open(STORE_ID_FILE, "w") as f:

        f.write(store_id)

    print(f"Saved store_id to {STORE_ID_FILE}")





if __name__ == "__main__":

    main()

