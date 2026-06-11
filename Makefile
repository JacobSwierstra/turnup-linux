.PHONY: rpm deb arch packages install test clean

rpm:
	./packaging/rpm/build-rpm.sh

deb:
	./packaging/debian/build-deb.sh

arch:
	./packaging/arch/build-arch.sh

packages: rpm deb arch

install:
	./install.sh

test:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v

clean:
	rm -rf build
