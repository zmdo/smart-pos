#!/bin/bash
set -uo pipefail
for u in https://commons.wikimedia.org https://upload.wikimedia.org https://images.unsplash.com https://images.pexels.com https://thispersondoesnotexist.com; do
  printf '%s -> ' "$u"
  timeout 12 curl -s -o /dev/null -w '%{http_code}\n' "$u" || echo FAIL
done
echo '--- commons api search ---'
timeout 20 curl -s -A 'Mozilla/5.0' 'https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6&gsrsearch=filetype:bitmap%20man%20walking%20away%20back%20view&gsrlimit=5&prop=imageinfo&iiprop=url|size&iiurlwidth=1200' | head -c 2000
echo
echo '--- unsplash search page ---'
timeout 20 curl -s -A 'Mozilla/5.0' 'https://unsplash.com/s/photos/man-back-view' | grep -o 'https://images.unsplash.com/photo-[a-z0-9-]*' | head -5
