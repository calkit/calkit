%% v1.0 (SGLS) 12/97
% Stefan Llewellyn Smith, sgls1@damtp.cam.ac.uk
% See readme in jfm style distribution.
%%
%%v1.1 revised 12/2005 to fix second initial problem, as suggested by
%%Christian Schoof
%%
%% This is file `jfmraw.bst',
%% generated with the docstrip utility.
%%
%% The original source files were:
%%
%% merlin.mbs  (with options: `,ay,nat,vonx,nm-rev,nmft-sc,dt-beg,yr-blk,yrp-x,note-yr,thtit-a,vol-bf,vnum-sp,volp-com,jnm-x,add-pub,pre-edn,edby-par,edbyx,blk-tit,pp,ed,abr,ord,xlab-it,amper,and-xcom,etal-it')
%% ----------------------------------------
%% *** JFM basic style ***
%%
  %-------------------------------------------------------------------
  % The original source file contains the following version information:
  % \ProvidesFile{merlin.mbs}[1997/06/09 3.83 (PWD)]
  %
  % NOTICE:
  % This file may be used for non-profit purposes.
  % It may not be distributed in exchange for money,
  %   other than distribution costs.
  %
  % The author provides it `as is' and does not guarantee it in any way.
  %
  % Copyright (C) 1994-97 Patrick W. Daly
  %           (C) 1997    Stefan G. Llewellyn Smith
  %-------------------------------------------------------------------
  %   For use with BibTeX version 0.99a or later
  %-------------------------------------------------------------------
  % This bibliography style file is intended for texts in ENGLISH
  % This is an author-year citation style bibliography. As such, it is
  % non-standard LaTeX, and requires a special package file to function properly.
  % Such a package is    natbib.sty   by Patrick W. Daly
  % The form of the \bibitem entries is
  %   \bibitem[Jones et al.(1990)]{key}...
  %   \bibitem[Jones et al.(1990)Jones, Baker, and Smith]{key}...
  % The essential feature is that the label (the part in brackets) consists
  % of the author names, as they should appear in the citation, with the year
  % in parentheses following. There must be no space before the opening
  % parenthesis!
  % With natbib v5.3, a full list of authors may also follow the year.
  % In natbib.sty, it is possible to define the type of enclosures that is
  % really wanted (brackets or parentheses), but in either case, there must
  % be parentheses in the label.
  % The \cite command functions as follows:
  %   \cite{key} ==>>                Jones et al. (1990)
  %   \cite[]{key} ==>>              (Jones et al., 1990)
  %   \cite[chap. 2]{key} ==>>       (Jones et al., 1990, chap. 2)
  %   \cite[e.g.][]{key} ==>>        (e.g. Jones et al., 1990)
  %   \cite[e.g.][p. 32]{key} ==>>   (e.g. Jones et al., p. 32)
  %   \citeauthor{key}               Jones et al.
  %   \citefullauthor{key}           Jones, Baker, and Smith
  %   \citeyear{key}                 1990
  %---------------------------------------------------------------------

ENTRY
   { address
     author
     booktitle
     chapter
     edition
     editor
     howpublished
     institution
     journal
     key
     month
     note
     number
     organization
     pages
     publisher
     school
     series
     title
     type
     volume
     year
     eprint
   }
   {}
   { label extra.label sort.label short.list }

INTEGERS { output.state before.all mid.sentence after.sentence after.block }

FUNCTION {init.state.consts}
{ #0 'before.all :=
   #1 'mid.sentence :=
   #2 'after.sentence :=
   #3 'after.block :=
}

STRINGS { s t }

FUNCTION {output.nonnull}
{ 's :=
   output.state mid.sentence =
     { ", " * write$ }
     { output.state after.block =
         { add.period$ write$
           newline$
           "\newblock " write$
         }
         { output.state before.all =
             'write$
             { add.period$ " " * write$ }
           if$
         }
       if$
       mid.sentence 'output.state :=
     }
   if$
   s
}

FUNCTION {output}
{ duplicate$ empty$
     'pop$
     'output.nonnull
   if$
}

FUNCTION {output.check}
{ 't :=
   duplicate$ empty$
     { pop$ "empty " t * " in " * cite$ * warning$ }
     'output.nonnull
   if$
}

FUNCTION {fin.entry}
{ add.period$
   write$
   newline$
}

FUNCTION {new.block}
{ output.state before.all =
     'skip$
     { after.block 'output.state := }
   if$
}

FUNCTION {new.sentence}
{ output.state after.block =
     'skip$
     { output.state before.all =
         'skip$
         { after.sentence 'output.state := }
       if$
     }
   if$
}

FUNCTION {add.blank}
{  " " * before.all 'output.state :=
}

FUNCTION {date.block}
{
   add.blank
}

FUNCTION {not}
{   { #0 }
     { #1 }
   if$
}

FUNCTION {and}
{   'skip$
     { pop$ #0 }
   if$
}

FUNCTION {or}
{   { pop$ #1 }
     'skip$
   if$
}

FUNCTION {new.block.checkb}
{ empty$
   swap$ empty$
   and
     'skip$
     'new.block
   if$
}

FUNCTION {field.or.null}
{ duplicate$ empty$
     { pop$ "" }
     'skip$
   if$
}

FUNCTION {emphasize}
{ duplicate$ empty$
     { pop$ "" }
     { "{\em " swap$ * "\/}" * }
   if$
}

FUNCTION {cmd@author}
{ duplicate$ empty$
     { pop$ "" }
     { "\au{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@editor}
{ duplicate$ empty$
     { pop$ "" }
     { "\ed{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@year}
{ duplicate$ empty$
     { pop$ "" }
     { " \yr{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@atitle}
{ duplicate$ empty$
     { pop$ "" }
     { " \at{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@jtitle}
{ duplicate$ empty$
     { pop$ "" }
     { " \jt{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@bktitle}
{ duplicate$ empty$
     { pop$ "" }
     { " \bt{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@seriestitle}
{ duplicate$ empty$
     { pop$ "" }
     { " \st{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@bvolume}
{ duplicate$ empty$
     { pop$ "" }
     { " \bvol{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@volume}
{ duplicate$ empty$
     { pop$ "" }
     { " \vol{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@pages}
{ duplicate$ empty$
     { pop$ "" }
     { " \pg{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@publisher}
{ duplicate$ empty$
     { pop$ "" }
     { " \publ{" swap$ * "}" * }
   if$
}

FUNCTION {cmd@arxiv}
{ duplicate$ empty$
     { pop$ "" }
     { " \arxiv{arXiv: " swap$ * "}" * }
   if$
}

FUNCTION {cmd@org}
{ duplicate$ empty$
     { pop$ "" }
     { " \org{" swap$ * "}" * }
   if$
}


FUNCTION {bolden}
{ duplicate$ empty$
     { pop$ "" }
     { "{\bf " swap$ * "}" * }
   if$
}

FUNCTION {scaps}
{ duplicate$ empty$
     { pop$ "" }
     { "{\sc " swap$ * "}" * }
   if$
}

FUNCTION {capitalize}
{ "u" change.case$ "t" change.case$ }

FUNCTION {space.word}
{ " " swap$ * " " * }

  % Here are the language-specific definitions for explicit words.
  % Each function has a name bbl.xxx where xxx is the English word.
  % The language selected here is ENGLISH
FUNCTION {bbl.and}
{ "and"}

FUNCTION {bbl.editors}
{ "ed." }

FUNCTION {bbl.editor}
{ "ed." }

FUNCTION {bbl.edby}
{ "edited by" }

FUNCTION {bbl.edition}
{ "edn." }

FUNCTION {bbl.volume}
{ "vol." }

FUNCTION {bbl.of}
{ "of" }

FUNCTION {bbl.number}
{ "" }

FUNCTION {bbl.nr}
{ "no." }

FUNCTION {bbl.in}
{ "in" }

FUNCTION {bbl.pages}
{ "pp." }

FUNCTION {bbl.page}
{ "p." }

FUNCTION {bbl.chapter}
{ "chap." }

FUNCTION {bbl.techrep}
{ "Tech. Rep." }

FUNCTION {bbl.mthesis}
{ "Master's thesis" }

FUNCTION {bbl.phdthesis}
{ "PhD thesis" }

FUNCTION {bbl.first}
{ "1st" }

FUNCTION {bbl.second}
{ "2nd" }

FUNCTION {bbl.third}
{ "3rd" }

FUNCTION {bbl.fourth}
{ "4th" }

FUNCTION {bbl.fifth}
{ "5th" }

FUNCTION {bbl.st}
{ "st" }

FUNCTION {bbl.nd}
{ "nd" }

FUNCTION {bbl.rd}
{ "rd" }

FUNCTION {bbl.th}
{ "th" }

MACRO {jan} {"Jan."}

MACRO {feb} {"Feb."}

MACRO {mar} {"Mar."}

MACRO {apr} {"Apr."}

MACRO {may} {"May"}

MACRO {jun} {"Jun."}

MACRO {jul} {"Jul."}

MACRO {aug} {"Aug."}

MACRO {sep} {"Sep."}

MACRO {oct} {"Oct."}

MACRO {nov} {"Nov."}

MACRO {dec} {"Dec."}

FUNCTION {eng.ord}
{ duplicate$ "1" swap$ *
   #-2 #1 substring$ "1" =
      { bbl.th * }
      { duplicate$ #-1 #1 substring$
        duplicate$ "1" =
          { pop$ bbl.st * }
          { duplicate$ "2" =
              { pop$ bbl.nd * }
              { "3" =
                  { bbl.rd * }
                  { bbl.th * }
                if$
              }
            if$
           }
        if$
      }
    if$
}

MACRO {acmcs} {"ACM Computing Surveys"}

MACRO {acta} {"Acta Informatica"}

MACRO {cacm} {"Communications of the ACM"}

MACRO {ibmjrd} {"IBM Journal of Research and Development"}

MACRO {ibmsj} {"IBM Systems Journal"}

MACRO {ieeese} {"IEEE Transactions on Software Engineering"}

MACRO {ieeetc} {"IEEE Transactions on Computers"}

MACRO {ieeetcad}
  {"IEEE Transactions on Computer-Aided Design of Integrated Circuits"}

MACRO {ipl} {"Information Processing Letters"}

MACRO {jacm} {"Journal of the ACM"}

MACRO {jcss} {"Journal of Computer and System Sciences"}

MACRO {scp} {"Science of Computer Programming"}

MACRO {sicomp} {"SIAM Journal on Computing"}

MACRO {tocs} {"ACM Transactions on Computer Systems"}

MACRO {tods} {"ACM Transactions on Database Systems"}

MACRO {tog} {"ACM Transactions on Graphics"}

MACRO {toms} {"ACM Transactions on Mathematical Software"}

MACRO {toois} {"ACM Transactions on Office Information Systems"}

MACRO {toplas} {"ACM Transactions on Programming Languages and Systems"}

MACRO {tcs} {"Theoretical Computer Science"}

INTEGERS { nameptr namesleft numnames }

FUNCTION {format.names}
{ 's :=
   #1 'nameptr :=
   s num.names$ 'numnames :=
   numnames 'namesleft :=
     { namesleft #0 > }
     { s nameptr
       "{vv~}{ll}{, jj}{, ff}" format.name$ cmd@author 't :=
       nameptr #1 >
         {
           namesleft #1 >
             { ", " * t * }
             {
               t "others" =
                 { " " * "et~al." emphasize * }
                 { " \& " * t * }
               if$
             }
           if$
         }
         't
       if$
       nameptr #1 + 'nameptr :=
       namesleft #1 - 'namesleft :=
     }
   while$
}

FUNCTION {format.names.ed}
{ 's :=
   #1 'nameptr :=
   s num.names$ 'numnames :=
   numnames 'namesleft :=
     { namesleft #0 > }
     { s nameptr
       "{ff~}{vv~}{ll}{, jj}"
       format.name$ 't :=
       nameptr #1 >
         {
           namesleft #1 >
             { ", " * t * }
             {
               t "others" =
                 { " " * "et~al." emphasize * }
                 { " \& " * t * }
               if$
             }
           if$
         }
         't
       if$
       nameptr #1 + 'nameptr :=
       namesleft #1 - 'namesleft :=
     }
   while$
}

FUNCTION {format.key}
{ empty$
     { key field.or.null }
     { "" }
   if$
}

FUNCTION {format.authors}
{ author empty$
     { "" }
     {
      author format.names scaps
     }
   if$
}

FUNCTION {format.editors}
{ editor empty$
     { "" }
     {
       editor format.names scaps
       editor num.names$ #1 >
         { ", " * bbl.editors * }
         { ", " * bbl.editor * }
       if$
     }
   if$
}

FUNCTION {format.in.editors}
{ editor empty$
     { "" }
     { editor format.names.ed cmd@editor
     }
   if$
}

FUNCTION {format.note}
{ note empty$
     { "" }
     { note #1 #1 substring$
       duplicate$ "{" =
         'skip$
         { output.state mid.sentence =
           { "l" }
           { "u" }
         if$
         change.case$
         }
       if$
       note #2 global.max$ substring$ *
     }
   if$
}

FUNCTION {format.title}
{ title empty$
     { "" }
     { title "t" change.case$
     }
   if$
}

FUNCTION {format.full.names}
{'s :=
   #1 'nameptr :=
   s num.names$ 'numnames :=
   numnames 'namesleft :=
     { namesleft #0 > }
     { s nameptr
       "{vv~}{ll}" format.name$ 't :=
       nameptr #1 >
         {
           namesleft #1 >
             { ", " * t * }
             {
               t "others" =
                 { " " * "et~al." emphasize * }
                 { " \& " * t * }
               if$
             }
           if$
         }
         't
       if$
       nameptr #1 + 'nameptr :=
       namesleft #1 - 'namesleft :=
     }
   while$
}

FUNCTION {author.editor.key.full}
{ author empty$
     { editor empty$
         { key empty$
             { cite$ #1 #3 substring$ }
             'key
           if$
         }
         { editor format.full.names }
       if$
     }
     { author format.full.names }
   if$
}

FUNCTION {author.key.full}
{ author empty$
     { key empty$
          { cite$ #1 #3 substring$ }
           'key
       if$
     }
     { author format.full.names }
   if$
}

FUNCTION {editor.key.full}
{ editor empty$
     { key empty$
          { cite$ #1 #3 substring$ }
           'key
       if$
     }
     { editor format.full.names }
   if$
}

FUNCTION {make.full.names}
{ type$ "book" =
   type$ "inbook" =
   or
     'author.editor.key.full
     { type$ "proceedings" =
         'editor.key.full
         'author.key.full
       if$
     }
   if$
}

FUNCTION {output.bibitem}
{ newline$
   "\bibitem[" write$
   label write$
   ")" make.full.names duplicate$ short.list =
      { pop$ }
      { * }
    if$
   "]{" * write$
   cite$ write$
   "}" write$
   newline$
   ""
   before.all 'output.state :=
}

FUNCTION {n.dashify}
{ 't :=
   ""
     { t empty$ not }
     { t #1 #1 substring$ "-" =
         { t #1 #2 substring$ "--" = not
             { "--" *
               t #2 global.max$ substring$ 't :=
             }
             {   { t #1 #1 substring$ "-" = }
                 { "-" *
                   t #2 global.max$ substring$ 't :=
                 }
               while$
             }
           if$
         }
         { t #1 #1 substring$ *
           t #2 global.max$ substring$ 't :=
         }
       if$
     }
   while$
}

FUNCTION {word.in}
{ bbl.in capitalize
   " " * }

FUNCTION {format.date}
{ year duplicate$ empty$
     { "empty year in " cite$ * "; set to ????" * warning$
        pop$ "????" }
     'skip$
   if$
   extra.label *
   before.all 'output.state :=
   "" swap$ * cmd@year
}

FUNCTION {format.btitle}
{ title emphasize
}

FUNCTION {tie.or.space.connect}
{ duplicate$ text.length$ #3 <
     { "~" }
     { " " }
   if$
   swap$ * *
}

FUNCTION {either.or.check}
{ empty$
     'pop$
     { "can't use both " swap$ * " fields in " * cite$ * warning$ }
   if$
}

FUNCTION {format.bvolume}
% Changed (SGLS)
% Notes swap$ fudge
{ volume empty$
     { "" }
     { series empty$
        { "" }
        { series cmd@seriestitle }
      if$
      swap$ bbl.volume volume tie.or.space.connect output cmd@volume
     }
   if$
}
%{ volume empty$
%    { "" }
%    { bbl.volume volume tie.or.space.connect
%      series empty$
%        'skip$
%        { bbl.of space.word * series emphasize * }
%      if$
%      "volume and number" number either.or.check
%    }
%  if$
%}

FUNCTION {format.number.series}
% Changed (SGLS)
{
  volume empty$
     { series empty$
         { ""
           number empty$
             'skip$
             { "there's a number but no series in " cite$ * warning$ }
           if$
         }
         { series emphasize " " * number *}
       if$
     }
     { "" }
   if$
}
%{ volume empty$
%    { number empty$
%        { series field.or.null }
%        { output.state mid.sentence =
%            { bbl.number }
%            { bbl.number capitalize }
%          if$
%          number tie.or.space.connect
%          series empty$
%            { "there's a number but no series in " cite$ * warning$ }
%            { bbl.in space.word * series * }
%          if$
%        }
%      if$
%    }
%    { "" }
%  if$
%}

FUNCTION {is.num}
{ chr.to.int$
   duplicate$ "0" chr.to.int$ < not
   swap$ "9" chr.to.int$ > not and
}

FUNCTION {extract.num}
{ duplicate$ 't :=
   "" 's :=
   { t empty$ not }
   { t #1 #1 substring$
     t #2 global.max$ substring$ 't :=
     duplicate$ is.num
       { s swap$ * 's := }
       { pop$ "" 't := }
     if$
   }
   while$
   s empty$
     'skip$
     { pop$ s }
   if$
}

FUNCTION {convert.edition}
{ edition extract.num "l" change.case$ 's :=
   s "first" = s "1" = or
     { bbl.first 't := }
     { s "second" = s "2" = or
         { bbl.second 't := }
         { s "third" = s "3" = or
             { bbl.third 't := }
             { s "fourth" = s "4" = or
                 { bbl.fourth 't := }
                 { s "fifth" = s "5" = or
                     { bbl.fifth 't := }
                     { s #1 #1 substring$ is.num
                         { s eng.ord 't := }
                         { edition 't := }
                       if$
                     }
                   if$
                 }
               if$
             }
           if$
         }
       if$
     }
   if$
   t
}

FUNCTION {format.edition}
{ edition empty$
     { "" }
     { output.state mid.sentence =
         { convert.edition "l" change.case$ " " * bbl.edition * }
         { convert.edition "t" change.case$ " " * bbl.edition * }
       if$
     }
   if$
}

INTEGERS { multiresult }

FUNCTION {multi.page.check}
{ 't :=
   #0 'multiresult :=
     { multiresult not
       t empty$ not
       and
     }
     { t #1 #1 substring$
       duplicate$ "-" =
       swap$ duplicate$ "," =
       swap$ "+" =
       or or
         { #1 'multiresult := }
         { t #2 global.max$ substring$ 't := }
       if$
     }
   while$
   multiresult
}

FUNCTION {format.pages}
{ pages empty$
     { "" }
     { pages multi.page.check
         { bbl.pages pages n.dashify tie.or.space.connect }
         { bbl.page pages tie.or.space.connect }
       if$
       cmd@pages
     }
   if$
}

FUNCTION {format.journal.pages}
{
   pages empty$
     'skip$
     { duplicate$ empty$
         { pop$ format.pages }
         { ", " * pages n.dashify cmd@pages * }
       if$
     }
   if$
}

FUNCTION {format.vol.num.pages}
{ volume field.or.null
%   bolden
   cmd@bvolume
   number empty$
     'skip$
     {
       "~(" number * ")" * *
       volume empty$
         { "there's a number but no volume in " cite$ * warning$ }
         'skip$
       if$
     }
   if$
   format.journal.pages
}

FUNCTION {format.chapter.pages}
{ chapter empty$
     'format.pages
     { type empty$
         { bbl.chapter }
         { type "l" change.case$ }
       if$
       chapter tie.or.space.connect
       pages empty$
         'skip$
         { ", " * format.pages * }
       if$
     }
   if$
}

FUNCTION {format.in.ed.booktitle}
% Changed to get edition after booktitle (SGLS)
% Notes swap$ fudge
{ booktitle empty$
     { "" }
     { word.in booktitle emphasize *
       edition empty$
	'skip$
         { swap$ format.edition output }
       if$
       editor empty$
         { "" * }
         {" (" *
           editor num.names$ #1 >
             { bbl.editors }
             { bbl.editor }
           if$
           *
           " " *
           format.in.editors *
           ")" *
         }
       if$
     }
   if$
}

FUNCTION {format.thesis.type}
{ type empty$
     'skip$
     { pop$
       type "t" change.case$
     }
   if$
}

FUNCTION {format.tr.number}
{ type empty$
     { bbl.techrep emphasize }
     'type
   if$
   number empty$
     { "t" change.case$ }
     { number tie.or.space.connect }
   if$
}

FUNCTION {format.article.crossref}
{
   word.in
   " \cite{" * crossref * "}" *
}

FUNCTION {format.book.crossref}
{ volume empty$
     { "empty volume in " cite$ * "'s crossref of " * crossref * warning$
       word.in
     }
     { bbl.volume capitalize
       volume tie.or.space.connect
       bbl.of space.word *
     }
   if$
   " \cite{" * crossref * "}" *
}

FUNCTION {format.incoll.inproc.crossref}
{
   word.in
   " \cite{" * crossref * "}" *
}

FUNCTION {format.publisher}
{ publisher empty$
     { "empty publisher in " cite$ * warning$ }
     'skip$
   if$
   ""
   address empty$ publisher empty$ and
     'skip$
     {
       address empty$
         'skip$
         { address * }
       if$
       publisher empty$
         'skip$
         { address empty$
             'skip$
             { ": " * }
           if$
           publisher *
         }
       if$
       cmd@publisher
     }
   if$
   output
}

FUNCTION {format.eprint}
{ eprint empty$
     { "" }
     { ", " * eprint cmd@arxiv * ""}
   if$
}

FUNCTION {article}
{ output.bibitem
   format.authors "author" output.check
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check  cmd@atitle
   new.sentence
   crossref missing$
     { journal cmd@jtitle
%       emphasize
       "journal" output.check
       add.blank
       format.vol.num.pages output
     }
     { format.article.crossref output.nonnull
     }
   if$
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {book}
{ output.bibitem
   author empty$
     { format.editors "author and editor" output.check
       editor format.key output
     }
     { format.authors output.nonnull
       crossref missing$
         { "author and editor" editor either.or.check }
         'skip$
       if$
     }
   if$
   format.date "year" output.check
   date.block
   format.btitle "title" output.check
% Added edition after title (SGLS)
   format.edition output
   crossref missing$
     { format.bvolume output
   new.sentence
       format.number.series output
%      format.edition output
   new.sentence
       format.publisher
     }
     {
   new.sentence
       format.book.crossref output.nonnull
     }
   if$
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {booklet}
{ output.bibitem
   format.authors output
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check
   new.sentence
   howpublished output
   address output
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {inbook}
{ output.bibitem
   author empty$
     { format.editors "author and editor" output.check
       editor format.key output
     }
     { format.authors output.nonnull
       crossref missing$
         { "author and editor" editor either.or.check }
         'skip$
       if$
     }
   if$
   format.date "year" output.check
   date.block
   format.btitle "title" output.check
% Added edition after title (SGLS)
   format.edition output
   crossref missing$
     {
       format.bvolume output
       format.chapter.pages "chapter and pages" output.check
   new.sentence
       format.number.series output
%      format.edition output
   new.sentence
       format.publisher
     }
     {
       format.chapter.pages "chapter and pages" output.check
   new.sentence
       format.book.crossref output.nonnull
     }
   if$
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {incollection}
{ output.bibitem
   format.authors "author" output.check
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check cmd@atitle
   new.sentence
   crossref missing$
     { format.in.ed.booktitle "booktitle" output.check cmd@bktitle
       format.bvolume output
       format.number.series output
%      format.edition output
       format.chapter.pages output
   new.sentence
       format.publisher
     }
     { format.incoll.inproc.crossref output.nonnull
       format.chapter.pages output
     }
   if$
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {inproceedings}
{ output.bibitem
   format.authors "author" output.check
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check
   new.sentence
   crossref missing$
     { format.in.ed.booktitle "booktitle" output.check cmd@bktitle
       format.bvolume output
       format.number.series output
       format.pages output
    new.sentence
       publisher empty$
         { organization output
           address output
         }
         { organization output
           format.publisher
         }
       if$
     }
     { format.incoll.inproc.crossref output.nonnull
       format.pages output
     }
   if$
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {conference} { inproceedings }

FUNCTION {manual}
{ output.bibitem
   format.authors output
   author format.key output
   format.date "year" output.check
   date.block
   format.btitle "title" output.check
% Added edition after title (SGLS)
   format.edition output
   new.sentence
   organization output
   address output
%  format.edition output
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {mastersthesis}
{ output.bibitem
   format.authors "author" output.check
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check
   new.sentence
   bbl.mthesis format.thesis.type output.nonnull
   school "school" output.check
   address output
   format.note output
   fin.entry
}

FUNCTION {misc}
{ output.bibitem
   format.authors output
   author format.key output
   format.date "year" output.check
   date.block
   format.title output
   new.sentence
   howpublished output
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {phdthesis}
{ output.bibitem
   format.authors "author" output.check
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check cmd@atitle
   new.sentence
   bbl.phdthesis format.thesis.type output.nonnull
   school "school" output.check
   address output
   format.note output
   fin.entry
}

FUNCTION {proceedings}
{ output.bibitem
   format.editors output
   editor format.key output
   format.date "year" output.check
   date.block
   format.btitle "title" output.check
   format.bvolume output
   format.number.series output
   address output
   organization output
   new.sentence
   publisher output
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {techreport}
{ output.bibitem
   format.authors "author" output.check
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check cmd@bktitle
   new.sentence
   format.tr.number output.nonnull
   new.sentence
   institution "institution" output.check cmd@org
   address output
   format.note output
   format.eprint output
   fin.entry
}

FUNCTION {unpublished}
{ output.bibitem
   format.authors "author" output.check
   author format.key output
   format.date "year" output.check
   date.block
   format.title "title" output.check
   new.sentence
   format.note "note" output.check
   format.eprint output
   fin.entry
}

FUNCTION {default.type} { misc }

READ

FUNCTION {sortify}
{ purify$
   "l" change.case$
}

INTEGERS { len }

FUNCTION {chop.word}
{ 's :=
   'len :=
   s #1 len substring$ =
     { s len #1 + global.max$ substring$ }
     's
   if$
}

FUNCTION {format.lab.names}
{ 's :=
   s #1 "{vv~}{ll}" format.name$
   s num.names$ duplicate$
   #2 >
     { pop$ " " * "et~al." emphasize * }
     { #2 <
         'skip$
         { s #2 "{ff }{vv }{ll}{ jj}" format.name$ "others" =
             { " " * "et~al." emphasize * }
             { " \& " * s #2 "{vv~}{ll}" format.name$ * }
           if$
         }
       if$
     }
   if$
}

FUNCTION {author.key.label}
{ author empty$
     { key empty$
         { cite$ #1 #3 substring$ }
         'key
       if$
     }
     { author format.lab.names }
   if$
}

FUNCTION {author.editor.key.label}
{ author empty$
     { editor empty$
         { key empty$
             { cite$ #1 #3 substring$ }
             'key
           if$
         }
         { editor format.lab.names }
       if$
     }
     { author format.lab.names }
   if$
}

FUNCTION {editor.key.label}
{ editor empty$
     { key empty$
         { cite$ #1 #3 substring$ }
         'key
       if$
     }
     { editor format.lab.names }
   if$
}

FUNCTION {calc.short.authors}
{ type$ "book" =
   type$ "inbook" =
   or
     'author.editor.key.label
     { type$ "proceedings" =
         'editor.key.label
         'author.key.label
       if$
     }
   if$
   'short.list :=
}

FUNCTION {calc.label}
{ calc.short.authors
   short.list
   "("
   *
   year duplicate$ empty$
      { pop$ "????" }
      'skip$
   if$
   *
   'label :=
}

FUNCTION {sort.format.names}
{ 's :=
   #1 'nameptr :=
   ""
   s num.names$ 'numnames :=
   numnames 'namesleft :=
     { namesleft #0 > }
     { s nameptr
       "{ll{ }}{  f{ }}{  jj{ }}"
       format.name$ 't :=
       nameptr #1 >
         {
           "   "  *
           namesleft #1 = t "others" = and
             { "zzzzz" * }
             { t sortify * }
           if$
         }
         { t sortify * }
       if$
       nameptr #1 + 'nameptr :=
       namesleft #1 - 'namesleft :=
     }
   while$
}

FUNCTION {sort.format.title}
{ 't :=
   "A " #2
     "An " #3
       "The " #4 t chop.word
     chop.word
   chop.word
   sortify
   #1 global.max$ substring$
}

FUNCTION {author.sort}
{ author empty$
     { key empty$
         { "to sort, need author or key in " cite$ * warning$
           ""
         }
         { key sortify }
       if$
     }
     { author sort.format.names }
   if$
}

FUNCTION {author.editor.sort}
{ author empty$
     { editor empty$
         { key empty$
             { "to sort, need author, editor, or key in " cite$ * warning$
               ""
             }
             { key sortify }
           if$
         }
         { editor sort.format.names }
       if$
     }
     { author sort.format.names }
   if$
}

FUNCTION {editor.sort}
{ editor empty$
     { key empty$
         { "to sort, need editor or key in " cite$ * warning$
           ""
         }
         { key sortify }
       if$
     }
     { editor sort.format.names }
   if$
}

FUNCTION {presort}
{ calc.label
   label sortify
   "    "
   *
   type$ "book" =
   type$ "inbook" =
   or
     'author.editor.sort
     { type$ "proceedings" =
         'editor.sort
         'author.sort
       if$
     }
   if$
   #1 entry.max$ substring$
   'sort.label :=
   sort.label
   *
   "    "
   *
   title field.or.null
   sort.format.title
   *
   #1 entry.max$ substring$
   'sort.key$ :=
}

ITERATE {presort}

SORT

STRINGS { last.label next.extra }

INTEGERS { last.extra.num number.label }

FUNCTION {initialize.extra.label.stuff}
{ #0 int.to.chr$ 'last.label :=
   "" 'next.extra :=
   #0 'last.extra.num :=
   #0 'number.label :=
}

FUNCTION {forward.pass}
{ last.label label =
     { last.extra.num #1 + 'last.extra.num :=
       last.extra.num int.to.chr$ 'extra.label :=
     }
     { "a" chr.to.int$ 'last.extra.num :=
       "" 'extra.label :=
       label 'last.label :=
     }
   if$
   number.label #1 + 'number.label :=
}

FUNCTION {reverse.pass}
{ next.extra "b" =
     { "a" 'extra.label := }
     'skip$
   if$
   extra.label 'next.extra :=
   extra.label
   emphasize
   duplicate$ empty$
     'skip$
     { "{\natexlab{" swap$ * "}}" * }
   if$
   'extra.label :=
   label extra.label * 'label :=
}

EXECUTE {initialize.extra.label.stuff}

ITERATE {forward.pass}

REVERSE {reverse.pass}

FUNCTION {bib.sort.order}
{ sort.label
   "    "
   *
   year field.or.null sortify
   *
   "    "
   *
   title field.or.null
   sort.format.title
   *
   #1 entry.max$ substring$
   'sort.key$ :=
}

ITERATE {bib.sort.order}

SORT

FUNCTION {begin.bib}
{ preamble$ empty$
     'skip$
     { preamble$ write$ newline$ }
   if$
   "\begin{thebibliography}{" number.label int.to.str$ * "}" *
   write$ newline$
"\expandafter\ifx\csname natexlab\endcsname\relax\def\natexlab#1{#1}\fi"
  write$ newline$
 "\def\au#1{#1} \def\ed#1{#1} \def\yr#1{#1}\def\at#1{#1}\def\jt#1{\textit{#1}} \def\bt#1{#1}\def\bvol#1{\textbf{#1}} \def\vol#1{#1} \def\pg#1{#1} \def\publ#1{#1}\def\arxiv#1{#1}\def\org#1{#1}\def\st#1{\textit{#1}}"
  write$ newline$
}

EXECUTE {begin.bib}

EXECUTE {init.state.consts}

ITERATE {call.type$}

FUNCTION {end.bib}
{ newline$
   "\end{thebibliography}" write$ newline$
}

EXECUTE {end.bib}
%% End of customized bst file
%%
%% End of file `jfmraw.bst'.
