.PHONY: help dev app install ios-web ios-dev test icons clean

help:
	@echo "make dev      - run the macOS app from source (window)"
	@echo "make app      - build dist/Ronic Reader.app, RonicReader-macOS.zip and RonicReader.dmg"
	@echo "make install  - same as 'make app' and copy the app to ~/Applications"
	@echo "make ios-web  - build the iPad/iPhone web app into build/ios-web"
	@echo "make ios-dev  - build and serve the web app at http://localhost:8080"
	@echo "make test     - run the tests"
	@echo "make icons    - regenerate the logo and icons"
	@echo "make clean    - remove build artifacts"

dev:
	.venv/bin/python -m ronic_reader.app

app:
	./scripts/package-macos.sh

install:
	INSTALL=1 ./scripts/package-macos.sh

ios-web:
	./scripts/build-ios-web.sh

ios-dev: ios-web
	cd build/ios-web && python3 -m http.server 8080

test:
	.venv/bin/pytest -q

icons:
	./branding/make-icons.sh

clean:
	rm -rf build dist
