![image alt](https://github.com/BooleanMuse/boardtyper_3d/blob/main/img/Boardtyper3D_Title.png?raw=true)

Boardtyper 3D is a Blender extension designed to automate the preparation, arrangement, and export of 3D game components directly into Tabletop Simulator (TTS). It generates the required `.obj` files, extracts textures, and compiles the final TTS `.json` save file, offering seamless local testing on Tabletop Simulator.

![image alt](https://github.com/BooleanMuse/boardtyper_3d/blob/main/img/Screenshot%204.png?raw=true)

## Features

* **TTS Component Typing:** Assign native TTS properties (Generic, Bag, Figurine, Coin, Board, Infinite, Dice, Chip) and materials directly in Blender.
* **Smart Bag System:** Create bags and automatically populate them with other scene objects.
* **Visibility Control:** Keep utility objects hidden from the table while keeping them available inside bags.
* **Auto-Layout Grid:** Automatically arrange spawned objects in a clean grid to prevent physics collisions upon loading the game.
* **Lua Injection:** Attach custom `.lua` scripts to any object directly from Blender's text editor or external files.
* **Export local:** Export locally for rapid testing on TTS.

![image alt](https://github.com/BooleanMuse/boardtyper_3d/blob/main/img/Screenshot%206.png?raw=true)

## Installation

1. Download the latest `boardtyper_3d-x.x.x.zip` from the Releases page.
2. Open Blender 4.2 or newer.
3. Go to `Edit > Preferences > Get Extensions`.
4. Click the drop-down menu in the top right corner and select `Install from Disk...`.
5. Select the downloaded `.zip` file.
6. When prompted, enable the extension and grant the necessary permissions (Network and Files) required for exporting and GitHub uploads.

## Step-by-Step Usage Guide

### 1. Object Settings (Panel 1)

Select any Mesh object in your scene and open the **Boardtyper 3D** tab in the 3D Viewport sidebar (N-panel).

* **Identity:** * Set the **Name**. This will rename the object in Blender and serve as the piece name in TTS.
  * Select the **Type** (e.g., Generic, Token, Bag) and **Material** (e.g., Plastic, Wood).
* **Visibility & Bag Rules:**
  * **Spawn in World:** Uncheck this if the piece should only exist inside a bag and not as a loose item on the table.
  * **Show in Bag Picker:** Uncheck this to hide the piece from the bag contents dropdown menu (useful for background models).
  * **Can be stored in a Bag:** Uncheck this to automatically generate Lua code that prevents players from placing this object into any bag.
* **Lua:** Enable "Inject Lua Script" to attach custom logic. You can load an external `.lua` file or paste the code directly.
* **Set:** Enable "Is Set" and increase the count to export multiple identical copies of the object.
* **Bag Contents:** If the object Type is set to "Bag" or "Infinite", a list will appear. Click the `+` button to add other named objects from your scene into this bag, specifying the quantity for each.

![image alt](https://github.com/BooleanMuse/boardtyper_3d/blob/main/img/Screenshot%201.png?raw=true)

### 2. Scene Objects Overview (Panel 2)

This panel provides a quick summary of all objects configured for export. 

* You can review their type, set multipliers, and current visibility flags.
* Click the `X` button next to any item to instantly remove Boardtyper properties from that object, reverting it to a standard Blender mesh.

![image alt](https://github.com/BooleanMuse/boardtyper_3d/blob/main/img/Screenshot%202.png?raw=true)

### 3. Scene & Export (Panel 3)

Configure the global parameters for your game and export the final files.

* **Save Info:** Define the "Game Name" (which sets the name of the output `.json`) and the local "Export Folder".
* **Auto-Layout Grid:** Define the spacing, columns, and origin point. Boardtyper will automatically arrange all top-level objects into this grid to prevent physical collisions when spawning in TTS.
* **LOCAL Export:** Uses `file:///` paths. Best for rapid prototyping on your own machine on TTS.

Once everything is configured, click the **Export** button. Boardtyper will process all meshes, materials, and Lua scripts, generating a ready-to-play `.json` file.

![image alt](https://github.com/BooleanMuse/boardtyper_3d/blob/main/img/Screenshot%203.png?raw=true)

## License & Credits

Developed by Skarmuse. 
Released under the SPDX:GPL-3.0-or-later license.
