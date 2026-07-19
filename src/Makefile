# Builds the Danish-English .dictionary bundle with Apple's
# Dictionary Development Kit (expected in ../tools/, see README).
#
#   make          build the dictionary into objects/
#   make install  copy it into ~/Library/Dictionaries
#   make release  zip it up for a GitHub release
#   make clean    remove build output

DICT_NAME		=	"Dansk-English"
DICT_SRC_PATH		=	DanishEnglish.xml
CSS_PATH		=	DanishEnglish.css
PLIST_PATH		=	DanishEnglishInfo.plist

DICT_BUILD_OPTS		=

DICT_BUILD_TOOL_DIR	=	../tools/Dictionary-Development-Kit
DICT_BUILD_TOOL_BIN	=	"$(DICT_BUILD_TOOL_DIR)/bin"

DICT_DEV_KIT_OBJ_DIR	=	./objects
export	DICT_DEV_KIT_OBJ_DIR

DESTINATION_FOLDER	=	~/Library/Dictionaries
RM			=	/bin/rm

all:
	"$(DICT_BUILD_TOOL_BIN)/build_dict.sh" $(DICT_BUILD_OPTS) $(DICT_NAME) $(DICT_SRC_PATH) $(CSS_PATH) $(PLIST_PATH)
	echo "Done."

install:
	echo "Installing into $(DESTINATION_FOLDER)".
	mkdir -p $(DESTINATION_FOLDER)
	ditto --noextattr --norsrc $(DICT_DEV_KIT_OBJ_DIR)/$(DICT_NAME).dictionary  $(DESTINATION_FOLDER)/$(DICT_NAME).dictionary
	touch $(DESTINATION_FOLDER)
	echo "Done."
	echo "Quit and reopen Dictionary.app, then enable Dansk-English in Settings."

release:
	cd $(DICT_DEV_KIT_OBJ_DIR) && zip -r -q Dansk-English.dictionary.zip Dansk-English.dictionary
	echo "Created $(DICT_DEV_KIT_OBJ_DIR)/Dansk-English.dictionary.zip"

clean:
	$(RM) -rf $(DICT_DEV_KIT_OBJ_DIR)
