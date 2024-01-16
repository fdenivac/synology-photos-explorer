# About Synology Photos API

The files in this folder are the minimal, slightly modified versions of the project [Synology API](https://github.com/N4S4/synology-api)

<img src="https://user-images.githubusercontent.com/33936751/100731387-99fffc00-33cb-11eb-833c-b6ab87177651.jpg" width="30%" height="30%">

# Modifications made to the initial project

- The changes made to the Synology API core concern the details of errors reported by the Photos API.

- The Photos class has been rewritten and completed.

- A DatePhoto class, independent of the Synology API, has been added to facilitate date manipulation...


# Photos API available methods (Photos class)

  ### General methods
  * get_userinfo
  * get_admin_settings
  * get_guest_settings

  #### methods on folders
  * list_folders
  * count_folders
  * lookup_folder
  * get_folder
  * photos_in_folder
  * count_photos_in_folder
  * share_team_folder

  #### methods on albums
  * list_albums
  * get_albums
  * count_albums
  * count_photos_in_album
  * suggest_condition
  * create_normal_album
  * delete_album
  * add_photos_to_album
  * delete_photos_from_album
  * delete_conditional_album
  * set_album_condition
  * share_album
  * photos_in_album

  * list_shareable_users_and_groups

  #### methods on filters
  * count_photos_with_filter
  * photos_with_filter
  * list_search_filters

  #### methods on photos
  * photos_from_ids
  * photo_download
  * thumbnail_download

  #### methods on keywords (search in geolocalisation address, filename, description, identifier, ...?)
  * count_keyword
  * search_keyword

  #### methods on tags (search in geolocalisation address, filename, description, identifier, ...?)
  * count_general_tags
  * general_tags
  * general_tag
  * count_photos_with_tag
  * photos_with_tag

  #### methods on timeline
  * get_timeline
  * photos_with_timeline