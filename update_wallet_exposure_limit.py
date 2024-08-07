import json
import os

def update_wallet_exposure_limit_in_folder(folder_path, new_limit):
  """Updates the 'wallet_exposure_limit' in all JSON config files within a folder.

  Args:
    folder_path: Path to the folder containing the JSON configuration files.
    new_limit: The desired new value for 'wallet_exposure_limit'.
  """

  for filename in os.listdir(folder_path):
    if filename.endswith(".json"):
      config_file = os.path.join(folder_path, filename)
      try:
        with open(config_file, 'r+') as file:
          data = json.load(file)

          # Update for both "long" and "short" sections
          data["long"]["wallet_exposure_limit"] = new_limit
          data["short"]["wallet_exposure_limit"] = new_limit

          file.seek(0)
          json.dump(data, file, indent=2)
          file.truncate()

        print(f"Successfully updated 'wallet_exposure_limit' to {new_limit} in {filename}")
      except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"Error processing {filename}: {e}")

# --- Example Usage ---
configs_folder = "configs/live"  # Set the path to your configs folder
new_wallet_exposure_limit = 0.3  # Set your desired limit 

update_wallet_exposure_limit_in_folder(configs_folder, new_wallet_exposure_limit)
