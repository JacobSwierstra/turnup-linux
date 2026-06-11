.PHONY: rpm test clean

rpm:
	./packaging/rpm/build-rpm.sh

test:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v

clean:
	rm -rf build
