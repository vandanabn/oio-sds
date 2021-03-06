// OpenIO SDS Go rawx
// Copyright (C) 2015-2019 OpenIO SAS
//
// This library is free software; you can redistribute it and/or
// modify it under the terms of the GNU Affero General Public
// License as published by the Free Software Foundation; either
// version 3.0 of the License, or (at your option) any later version.
//
// This library is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
// Lesser General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public
// License along with this program. If not, see <http://www.gnu.org/licenses/>.

package main

/*
Minimal interface to a file repository, where each file might have
some <key,value> properties.
*/

type repository interface {
	lock(ns, url string) error
	has(name string) (bool, error)
	get(name string) (fileReader, error)
	put(name string) (fileWriter, error)
	link(fromName, toName string) (fileWriter, error)
	del(name string) error
}

type fileReader interface {
	Read([]byte) (int, error)
	Close() error
	size() int64
	seek(int64) error
	getAttr(n string) ([]byte, error)
	check() (string, error)
}

type fileWriter interface {
	Write([]byte) (int, error)
	seek(int64) error
	commit() error
	abort() error
	setAttr(n string, v []byte) error
}
