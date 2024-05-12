REGISTRY_LOC=${1:-"/home/admin/cache/ieee"}
mkdir -p $REGISTRY_LOC
cd $REGISTRY_LOC
rm -f mam.csv* oui.csv* oui36.csv*
wget https://standards-oui.ieee.org/oui/oui.csv
wget https://standards-oui.ieee.org/oui28/mam.csv
wget https://standards-oui.ieee.org/oui36/oui36.csv
wc -l mam.csv* oui.csv* oui36.csv*
